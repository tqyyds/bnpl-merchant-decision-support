"""Causal TCN with nested temporal early stopping and per-seed final refit."""
import copy
import os
import random
import numpy as np
import pandas as pd
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
import torch
from torch import nn
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from .contracts import CATEGORIES, metrics

SEEDS=(30034,30035,30036)

class SequenceTransform:
    def fit(self,x,s):
        self.encoder=OneHotEncoder(handle_unknown='ignore',sparse_output=False).fit(x[CATEGORIES])
        self.static_scaler=StandardScaler().fit(x[['hist_revenue_proxy_log1p']])
        a=np.log1p(s[:,:,[0,1,2,3,5]].astype(np.float64))
        self.mean=a.mean(axis=(0,1)); self.std=a.std(axis=(0,1)); self.std[self.std==0]=1
        return self
    def transform(self,x,s):
        a=s.astype(np.float32).copy()
        a[:,:,[0,1,2,3,5]]=(np.log1p(a[:,:,[0,1,2,3,5]])-self.mean)/self.std
        static=np.column_stack([self.encoder.transform(x[CATEGORIES]),x.take_rate_pct/100,self.static_scaler.transform(x[['hist_revenue_proxy_log1p']])]).astype(np.float32)
        return np.transpose(a,(0,2,1)).copy(),static

class CausalConv(nn.Module):
    def __init__(self,cin,cout,dilation):
        super().__init__(); self.pad=2*dilation
        self.conv=nn.Conv1d(cin,cout,3,dilation=dilation)
    def forward(self,x): return self.conv(nn.functional.pad(x,(self.pad,0)))

class Block(nn.Module):
    def __init__(self,cin,dilation):
        super().__init__()
        self.layers=nn.Sequential(CausalConv(cin,16,dilation),nn.ReLU(),nn.Dropout(.1),CausalConv(16,16,dilation),nn.ReLU(),nn.Dropout(.1))
        self.skip=nn.Conv1d(cin,16,1) if cin!=16 else nn.Identity()
    def forward(self,x): return torch.relu(self.layers(x)+self.skip(x))

class Network(nn.Module):
    def __init__(self,static_dim):
        super().__init__(); self.blocks=nn.Sequential(*[Block(6 if i==0 else 16,d) for i,d in enumerate((1,2,4,8))])
        self.head=nn.Sequential(nn.Linear(16+static_dim,32),nn.ReLU(),nn.Linear(32,1))
    def forward(self,s,a): return self.head(torch.cat([self.blocks(s)[:,:,-1],a],dim=1)).squeeze(1)

def seed_all(seed):
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark=False; torch.backends.cudnn.deterministic=True
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(4)

def predict_network(model,transform,x,s,device):
    a,b=transform.transform(x,s); model.eval(); result=[]
    with torch.no_grad():
        for start in range(0,len(x),1024):
            p=model(torch.as_tensor(a[start:start+1024],device=device),torch.as_tensor(b[start:start+1024],device=device))
            result.extend(p.cpu().numpy())
    p=np.maximum(0,np.expm1(np.asarray(result,dtype=np.float64)))
    if not np.isfinite(p).all(): raise ValueError('TCN prediction overflow')
    return p

def train_seed(x,y,s,seed,epochs=100,validation=None):
    seed_all(seed); device='cuda' if torch.cuda.is_available() else 'cpu'
    transform=SequenceTransform().fit(x,s); a,b=transform.transform(x,s)
    a=torch.as_tensor(a,device=device); b=torch.as_tensor(b,device=device)
    target=torch.as_tensor(np.log1p(np.asarray(y)),dtype=torch.float32,device=device)
    model=Network(b.shape[1]).to(device); optimiser=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.0001)
    best=-np.inf; best_epoch=0; stale=0; trace=[]
    for epoch in range(1,epochs+1):
        model.train(); order=torch.randperm(len(x),device=device); loss_sum=0.
        for ids in order.split(256):
            optimiser.zero_grad(set_to_none=True); p=model(a[ids],b[ids]); loss=nn.functional.mse_loss(p,target[ids])
            if not torch.isfinite(loss): raise ValueError('Nonfinite TCN loss')
            loss.backward(); nn.utils.clip_grad_norm_(model.parameters(),1.); optimiser.step(); loss_sum+=float(loss.detach())*len(ids)
        row={'epoch':epoch,'train_log_mse':loss_sum/len(x)}
        if validation is not None:
            vx,vy,vs=validation; prediction=predict_network(model,transform,vx,vs,device)
            m=vx[['merchant_abn','cutoff']].copy(); m['target_revenue']=np.asarray(vy); m['prediction']=prediction
            score=metrics(m)['ndcg']; row['early_stop_ndcg']=score
            if score>best:
                best,best_epoch,stale=score,epoch,0
            else: stale+=1
        trace.append(row)
        if epoch%10==0 or epoch==1: print(f'TCN seed={seed} epoch={epoch} loss={row["train_log_mse"]:.4f} best_epoch={best_epoch}',flush=True)
        if validation is not None and stale>=10: break
    model=model.cpu()
    return model,transform,best_epoch if validation is not None else epochs,trace

class Ensemble:
    def fit(self,x,y,s):
        dates=sorted(x.cutoff.unique()); inner=x.cutoff.lt(dates[-1]).to_numpy(); hold=~inner
        self.members=[]; self.evidence=[]
        for seed in SEEDS:
            _,_,epochs,trace=train_seed(x.loc[inner],np.asarray(y)[inner],s[inner],seed,
                validation=(x.loc[hold],np.asarray(y)[hold],s[hold]))
            print(f'TCN refit seed={seed}: all {len(dates)} cutoffs, {epochs} fixed epochs',flush=True)
            model,transform,_,refit=train_seed(x,y,s,seed,epochs=epochs)
            self.members.append((model,transform))
            self.evidence.append({'seed':seed,'epoch_selection_train_cutoffs':[str(pd.Timestamp(d).date()) for d in dates[:-1]],
                'epoch_selection_cutoff':str(pd.Timestamp(dates[-1]).date()),'selected_epochs':epochs,
                'refit_cutoffs':[str(pd.Timestamp(d).date()) for d in dates], 'refit_rows':len(x),'early_stop_trace':trace,'refit_trace':refit})
        return self
    def predict(self,x,s):
        return np.mean([predict_network(m,t,x,s,'cpu') for m,t in self.members],axis=0)
