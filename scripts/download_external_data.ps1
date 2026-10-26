$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$downloads = @(
    @{ Uri = 'https://www.abs.gov.au/census/find-census-data/datapacks/download/2021_GCP_POA_for_AUS_short-header.zip'; Path = 'tables/raw/external/primary/2021_GCP_POA_for_AUS_short-header.zip' },
    @{ Uri = 'https://www.abs.gov.au/statistics/people/people-and-communities/socio-economic-indexes-areas-seifa-australia/2021/Postal%20Area%2C%20Indexes%2C%20SEIFA%202021.xlsx'; Path = 'tables/raw/external/primary/SEIFA_2021_POA.xlsx' },
    @{ Uri = 'https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs/edition-3-july-2021-june-2026/access-and-downloads/digital-boundary-files/POA_2021_AUST_GDA2020_SHP.zip'; Path = 'tables/raw/external/primary/POA_2021_AUST_GDA2020_SHP.zip' },
    @{ Uri = 'https://data.gov.au/data/dataset/6cd8989d-4aca-46b7-b93e-77befcffa0b6/resource/cb659d81-5bd2-41f5-a3d0-67257c9a5893/download/asgs2021codingindexs.zip'; Path = 'tables/raw/external/sensitivity/ASGS2021CodingIndexes.zip' },
    @{ Uri = 'https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs/edition-3-july-2021-june-2026/access-and-downloads/digital-boundary-files/SA2_2021_AUST_SHP_GDA2020.zip'; Path = 'tables/raw/external/sensitivity/SA2_2021_AUST_GDA2020_SHP.zip' },
    @{ Uri = 'https://www.abs.gov.au/statistics/people/population/regional-population/2021-22/32180DS0003_2001-22r.xlsx'; Path = 'tables/raw/external/sensitivity/Regional_Population_2001_2022_SA2.xlsx' },
    @{ Uri = 'https://www.rba.gov.au/publications/rdp/2023/pdf/rdp2023-08.pdf'; Path = 'tables/raw/external/context/RBA_2022_Consumer_Payments_Survey.pdf' },
    @{ Uri = 'https://download.asic.gov.au/media/5852803/rep672-published-16-november-2020-2.pdf'; Path = 'tables/raw/external/context/ASIC_REP_672_BNPL.pdf' }
)

foreach ($item in $downloads) {
    $repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $destination = Join-Path $repositoryRoot $item.Path
    $destination = [System.IO.Path]::GetFullPath($destination)
    $directory = Split-Path -Parent $destination
    New-Item -ItemType Directory -Force -Path $directory | Out-Null

    if (Test-Path -LiteralPath $destination) {
        Write-Host "SKIP (exists): $destination"
        continue
    }

    Write-Host "DOWNLOAD: $($item.Uri)"
    Invoke-WebRequest -Uri $item.Uri -OutFile $destination
}

Write-Host 'Downloads complete. Run the audit notebook to verify registered hashes and structures.'
