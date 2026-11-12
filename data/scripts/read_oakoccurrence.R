library(tidyverse)
library(here)
library(lingtypology)
library(CoordinateCleaner)
library(sf)

# Load data on oaks and acorns. Manually retrieved from Table 7.1 in Brown (2001).
# We assigned glottocodes manually to get coordinates for each language.

oaks <- read_csv(here("data", "brown_oakacorn.csv")) %>%
  left_join(glottolog %>% select(glottocode, language, area, affiliation, latitude, longitude), by = "glottocode") %>%
  mutate(
    NBOT = SOT - BOT,
    family = str_extract(affiliation, "^[^,]+"),
    family = if_else(is.na(family), paste0("isolate_", glottocode), family),
    # Glottolog longitude needs to be corrected for all languages
    longitude = longitude - 360
  ) %>%
  select(-affiliation)

# Chumash is missing coordinates because it is now considered a language family.
# Use Mutsun's coordinate and assign Chumashan family.
oaks <- oaks %>%
  mutate(
    longitude = ifelse(glottocode == "chum1264", -121.45, longitude),
    latitude  = ifelse(glottocode == "chum1264", 36.85,   latitude),
    family    = ifelse(glottocode == "chum1264", "Chumashan", family)
  )

# Load GBIF oak occurrence data
oakoccur <- read_tsv(here("data", "gbif_quercus.csv"))

# Apply all recommended GBIF filters to address known data quality issues
oakoccur_filtered <- oakoccur %>%
  filter(genus == "Quercus") %>%
  setNames(tolower(names(.))) %>%
  filter(occurrencestatus == "PRESENT") %>%
  filter(!basisofrecord %in% c("FOSSIL_SPECIMEN", "LIVING_SPECIMEN")) %>%
  filter(year >= 1900) %>%
  filter(coordinateprecision < 0.01 | is.na(coordinateprecision)) %>%
  filter(coordinateuncertaintyinmeters < 10000 | is.na(coordinateuncertaintyinmeters)) %>%
  filter(!coordinateuncertaintyinmeters %in% c(301, 3036, 999, 9999)) %>%
  filter(!decimallatitude == 0 | !decimallongitude == 0) %>%
  distinct(decimallongitude, decimallatitude, specieskey, datasetkey, .keep_all = TRUE)

occur_filtered <- oakoccur_filtered %>%
  rename(decimalLongitude = decimallongitude, decimalLatitude = decimallatitude) %>%
  cc_cen(buffer = 2000) %>%  # remove country centroids within 2km
  cc_cap(buffer = 2000) %>%  # remove capital centroids within 2km
  cc_inst(buffer = 2000)     # remove zoos and herbaria within 2km

oakpresent <- occur_filtered %>%
  rename(decimallongitude = decimalLongitude, decimallatitude = decimalLatitude) %>%
  filter(!is.na(decimallatitude) & !is.na(decimallongitude)) %>%
  group_by(genus, species, taxonrank, decimallatitude, decimallongitude) %>%
  summarise(occurrence = n(),
            min_year   = min(year),
            max_year   = max(year)) %>%
  ungroup() %>%
  rename(latitude = decimallatitude, longitude = decimallongitude)

# Load glottography traditional language polygons
# Source: digital dataset derived from Asher & Moseley's Atlas of the World's Languages
glottography <- st_read(here("data", "glottography", "traditional", "languages.geojson"), quiet = TRUE) %>%
  rename(glottocode = `cldf.languageReference`) %>%
  select(glottocode)

oak_glottocodes <- unique(oaks$glottocode)
has_polygon     <- oak_glottocodes[oak_glottocodes %in% glottography$glottocode]
no_polygon      <- oak_glottocodes[!oak_glottocodes %in% glottography$glottocode]

cat("Languages with glottography polygon:", length(has_polygon), "\n")
cat("Languages without glottography polygon:", length(no_polygon), "\n")

# Territory polygons from glottography; compute area
poly_territories <- glottography %>%
  filter(glottocode %in% has_polygon) %>%
  mutate(
    area_km2   = as.numeric(st_area(st_transform(., 6933))) / 1e6,
    radius_km  = sqrt(area_km2 / pi),
    source     = "glottography"
  )

# 50km circular buffer for languages without glottography polygons
oaks_no_poly <- oaks %>%
  filter(glottocode %in% no_polygon, !is.na(longitude), !is.na(latitude)) %>%
  select(glottocode, latitude, longitude) %>%
  distinct()

buffer_territories <- st_as_sf(oaks_no_poly, coords = c("longitude", "latitude"), crs = 4326) %>%
  st_buffer(dist = 50000) %>%
  mutate(
    area_km2   = pi * 50^2,
    radius_km  = 50,
    source     = "buffer_50km"
  ) %>%
  select(glottocode, area_km2, radius_km, source)

# Combine polygon and buffer territories
all_territories <- bind_rows(poly_territories, buffer_territories)

oakpresent_sf <- st_as_sf(oakpresent, coords = c("longitude", "latitude"), crs = 4326)

joined_sf <- st_join(oakpresent_sf, all_territories, join = st_within) %>%
  filter(!is.na(glottocode))

byspecies <- joined_sf %>%
  filter(!is.na(species)) %>%
  group_by(glottocode, species) %>%
  summarise(
    occurrence = sum(occurrence),
    min_year   = min(min_year),
    max_year   = max(max_year)
  ) %>%
  ungroup() %>%
  left_join(oaks, by = "glottocode") %>%
  left_join(
    all_territories %>% st_drop_geometry() %>% select(glottocode, area_km2, radius_km, source),
    by = "glottocode"
  ) %>%
  unique()

byspecies <- as.data.frame(byspecies)

# Check temporal coverage per language
years_covered <- byspecies %>%
  group_by(glottocode, langname, subarea, area_km2, radius_km) %>%
  summarise(
    occurrence    = sum(occurrence, na.rm = TRUE),
    species       = n_distinct(species),
    min_year      = min(min_year),
    max_year      = max(max_year),
    years_covered = max_year - min_year + 1
  ) %>%
  ungroup()
setdiff(unique(oaks$glottocode), unique(byspecies$glottocode))
# all languages have oak occurrence information

byspecies %>%
  write_csv(here("data", "oak_occurrences.csv"))
