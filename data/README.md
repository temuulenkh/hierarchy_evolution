
# Manually created data

* `brown_oakacorn.csv` :  manually retrieved from Table 7.1 in Brown, C. H. (2001). Linguistic Ethnobiology. Ethnobiology at the millennium: past promise and future prospects, 91, 111.

# Downloaded data

* `gbif_quercus.csv` : was downloaded from GBIF.org on 26 June 2026 (https://doi.org/10.15468/dl.xkw5tk).
* `subsistence.csv` : was downloaded on 19 June 2026 from https://github.com/cskemp/lexical_elaboration/tree/main/data/forpreprocessing. 
* `d_full.csv` : was downloaded on 29 April 2026 from https://github.com/temuulenkh/lexicalization/tree/master/data. 
* `wnai`: was downloaded on 25 June 2026 from https://github.com/D-PLACE/dplace-data/tree/master/datasets/WNAI. 
* `glottography`: was downloaded on 6 July 2026 from https://zenodo.org/records/18613195. 

# Data created using scripts

* `naeb_quercus.csv` and `naeb_tribes.csv`: were created by running `scripts/scrape_naeb.py` on 7 July 2026. These files contain data based on Native American Ethnobotany dataset. From command line, it needs to run `python3 scrape_naeb.py tribes` and `python3 scrape_naeb.py quercus --genus Quercus --output naeb_quercus.csv` to produce these files.
* `oak_occurrences.csv` was created by running `scripts/read_oakoccurrence.R`.

