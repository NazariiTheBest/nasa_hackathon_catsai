# Spec Delta

## Purpose

Fuses climate series, satellite time series and soil properties into a diagnosis of a site: when its soil is exposed, when its crops are vulnerable, and how its water and temperature conditions are trending.

## ADDED Requirements

### Requirement: Data tier
Every diagnosis SHALL state its data tier: `field` when the location lies in a showcase field, `grid` when it lies only in a national grid cell, and `climate_only` when no unit contains it. A diagnosis SHALL be produced in every tier for which climate data is available.

#### Scenario: Location inside a showcase field
- **WHEN** a site inside a showcase field is diagnosed
- **THEN** the diagnosis reports tier `field` and identifies the field

#### Scenario: Location inside the grid only
- **WHEN** a site inside a grid cell and outside every showcase field is diagnosed
- **THEN** the diagnosis reports tier `grid` and identifies the cell

#### Scenario: Location outside all bundles
- **WHEN** a site outside every loaded unit is diagnosed
- **THEN** the diagnosis reports tier `climate_only` and is still produced from climate data

### Requirement: Bare-soil windows from the rotation calendar
The system SHALL report each period between the harvest of one crop and the sowing of the next in the rotation as a bare-soil window, with its start, end and length in days. A crop that grows across the turn of the calendar year SHALL be treated as continuous cover for its whole growing period.

#### Scenario: Long gap after a winter cereal
- **WHEN** a rotation has winter wheat harvested in July followed by sunflower sown the next April
- **THEN** a bare-soil window from that harvest to that sowing, about nine months long, is reported

#### Scenario: Winter crop is not reported as bare
- **WHEN** a rotation contains winter wheat sown in September and harvested the following July
- **THEN** no bare-soil window is reported between that sowing and that harvest

### Requirement: Observed low-cover periods
When a vegetation-index time series exists for the unit, the system SHALL report the day-of-year periods in which the multi-year median index is below the configured bare-soil threshold, together with the median value and the number of years observed. In tier `climate_only` this output SHALL be absent.

#### Scenario: Low-cover period detected from the index
- **WHEN** a unit's multi-year median vegetation index is below the threshold from early November to mid March
- **THEN** a low-cover period spanning those dates is reported with the number of years observed

#### Scenario: No time series available
- **WHEN** a site in tier `climate_only` is diagnosed
- **THEN** no observed low-cover periods are reported and the absence is recorded as an information gap

### Requirement: Erosion exposure of bare-soil windows
Each bare-soil window SHALL carry a relative erosion-exposure index between 0 and 1 that increases with the erosive rainfall falling inside the window and, when soil and terrain properties are available, with slope and soil erodibility. When those properties are unavailable the index SHALL be computed from rainfall alone and marked accordingly.

#### Scenario: Wetter window scores higher
- **WHEN** two bare-soil windows of equal length on the same site differ only in that one receives more erosive rainfall
- **THEN** the window with more erosive rainfall has the higher index

#### Scenario: Rainfall-only index is marked
- **WHEN** a bare-soil window is evaluated in tier `climate_only`
- **THEN** its index is computed from rainfall alone and is marked as lacking slope and soil inputs

### Requirement: Crop stress calendar
For each crop in the rotation and each applicable hazard (heat, frost, winterkill, drought), the system SHALL report the growth stage at risk, the probability that the hazard occurs in that stage, and the number of historical years in which it occurred out of the number examined.

#### Scenario: Heat during the sensitive stage
- **WHEN** the crop's heat threshold is exceeded during its sensitive stage in 12 of 36 historical years
- **THEN** the calendar reports a heat probability of 0.33 with 12 of 36 years

#### Scenario: Hazard that does not apply is omitted
- **WHEN** a spring-sown crop is evaluated
- **THEN** no winterkill entry is reported for it

### Requirement: Reference evapotranspiration and crop water balance
The system SHALL compute daily reference evapotranspiration by the FAO-56 Penman-Monteith method and SHALL report, for each crop in the rotation, the typical seasonal water demand, the water supplied by rainfall and soil storage, and the resulting deficit in millimeters.

#### Scenario: Published worked example is reproduced
- **WHEN** reference evapotranspiration is computed for the inputs of the FAO-56 daily worked example
- **THEN** the result matches the published value within 0.1 mm per day

#### Scenario: Days without radiation data
- **WHEN** solar radiation is missing for some days in the series
- **THEN** a temperature-based estimate is used for those days and their count is reported

### Requirement: Long-term trends
The system SHALL report trends in growing-season mean temperature, growing-season precipitation, growing-season precipitation minus reference evapotranspiration, the annual count of hot days and summer root-zone soil wetness. Each trend SHALL state the slope per decade, a p-value, the period analyzed and whether it is statistically significant, using a method that is robust to outliers.

#### Scenario: Known trend is recovered
- **WHEN** a 40-year series constructed with a slope of 0.4 units per decade plus noise is analyzed
- **THEN** the reported slope is within 0.1 of 0.4 per decade and the trend is marked significant

#### Scenario: Trendless series is not marked significant
- **WHEN** a 40-year series of independent noise with no trend is analyzed
- **THEN** the trend is marked not significant

### Requirement: Short records are not presented as trends
A series shorter than 15 years SHALL be summarized as anomalies relative to its own mean and SHALL NOT be reported with a trend slope or significance.

#### Scenario: Satellite soil moisture record
- **WHEN** a unit has a satellite soil-moisture series beginning in 2015
- **THEN** recent conditions are reported as anomalies against the series mean and no trend is reported for it

### Requirement: Soil properties and their provenance
When a unit's water-holding capacity or erodibility is not supplied, the system SHALL derive it from soil texture and organic carbon and mark it as derived. When no soil data exists at all, the system SHALL use a stated default water-holding capacity and mark it as assumed.

#### Scenario: Capacity derived from texture
- **WHEN** a unit supplies clay, sand and organic carbon but no water-holding capacity
- **THEN** a capacity is derived and reported as derived

#### Scenario: No soil data
- **WHEN** a site in tier `climate_only` is diagnosed
- **THEN** the default water-holding capacity is used and reported as assumed
