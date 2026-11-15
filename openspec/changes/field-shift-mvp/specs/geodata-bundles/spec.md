# Spec Delta

## Purpose

Defines the file contract through which pre-processed Earth-observation features for national grid cells and showcase fields enter the system, how those files are validated, and how a location is matched to the unit that contains it.

## ADDED Requirements

### Requirement: Bundle structure
A bundle SHALL be a directory containing a manifest, a units file, a time-series table and a static-properties table. A crop-history table and a suitability table are optional. The manifest SHALL state the contract version, the bundle identifier, the unit type, the author, the creation time and, for each variable, the source product, its version, native resolution and date range.

#### Scenario: Complete bundle is accepted
- **WHEN** a bundle containing all four required files with valid content is validated
- **THEN** validation succeeds and reports the number of units, variables and rows found

#### Scenario: Missing required file is rejected
- **WHEN** a bundle without its static-properties table is validated
- **THEN** validation fails and the report names the missing file

#### Scenario: Unsupported contract version is rejected
- **WHEN** a bundle whose manifest declares a contract version the system does not support is validated
- **THEN** validation fails and the report states the declared version and the supported version

### Requirement: Unit identity and geometry
Every unit SHALL have a unique string identifier, a unit type of `field` or `grid_cell`, and a polygon geometry in WGS84 with coordinates in longitude, latitude order.

#### Scenario: Duplicate unit identifiers are rejected
- **WHEN** a units file contains two units with the same identifier
- **THEN** validation fails and the report names the duplicated identifier

#### Scenario: Coordinates outside WGS84 bounds are rejected
- **WHEN** a units file contains a geometry with a longitude outside -180 to 180 or a latitude outside -90 to 90
- **THEN** validation fails and the report says the geometry is not in WGS84 longitude, latitude order

### Requirement: Long-format time series with a controlled vocabulary
The time-series table SHALL hold one row per unit, date and variable, with the value, its within-unit spread, the fraction of valid pixels, the source product and the native resolution. Variable names SHALL come from the contract's controlled vocabulary, and each variable SHALL be expressed in the single unit the vocabulary assigns to it.

#### Scenario: Unknown variable is rejected
- **WHEN** a time-series table contains a row whose variable is not in the controlled vocabulary
- **THEN** validation fails and the report names the unknown variable and lists the allowed ones

#### Scenario: Additional vocabulary variable needs no structural change
- **WHEN** a bundle that previously held only vegetation-index rows is delivered again with evapotranspiration rows added
- **THEN** validation succeeds without any change to the table's columns

### Requirement: Value validity
Every non-null value SHALL lie inside the valid range the vocabulary defines for its variable, missing data SHALL be represented as null, and the valid-pixel fraction SHALL lie between 0 and 1. Sentinel fill values SHALL NOT appear as data.

#### Scenario: Unscaled satellite integer is rejected
- **WHEN** a vegetation-index row holds the value 4200
- **THEN** validation fails and the report states the valid range and suggests that a scale factor was not applied

#### Scenario: Sentinel fill value is rejected
- **WHEN** a row holds the value -9999
- **THEN** validation fails and the report says missing data must be null

### Requirement: Referential integrity
Every unit identifier used in the time-series, static-properties, crop-history and suitability tables SHALL exist in the units file, and every unit in the units file SHALL have exactly one row in the static-properties table.

#### Scenario: Orphan unit identifier is rejected
- **WHEN** the time-series table references a unit identifier that is absent from the units file
- **THEN** validation fails and the report names the orphan identifier and the table it appears in

#### Scenario: Unit without static properties is rejected
- **WHEN** a unit in the units file has no row in the static-properties table
- **THEN** validation fails and the report names the unit

### Requirement: Standalone validation report
The system SHALL provide a validator that a data producer can run on a bundle without starting any other part of the system. It SHALL report every violation it finds, each with the file, the affected field or row and the reason, and SHALL signal failure through its exit status.

#### Scenario: All violations are reported together
- **WHEN** a bundle with an unknown variable and an orphan unit identifier is validated
- **THEN** the report lists both violations and the validator exits with a failure status

#### Scenario: Valid bundle exits successfully
- **WHEN** a valid bundle is validated
- **THEN** the validator exits with a success status

### Requirement: Conversion from Earth Engine export tables
The system SHALL convert a table with one row per unit and date and one column per band into the long-format time-series table, given a declared mapping from each band to a variable, a scale factor, a source product and a native resolution.

#### Scenario: Wide table is converted and scaled
- **WHEN** a table with columns for unit, date, NDVI and EVI holding integers scaled by 10000 is converted with a mapping that declares a scale factor of 0.0001
- **THEN** the output has one row per unit, date and variable with values between -1 and 1 and passes validation

#### Scenario: Unmapped band is reported
- **WHEN** the input table has a band column that the mapping does not mention
- **THEN** the conversion reports the unmapped column and does not silently include or drop it

### Requirement: Location lookup
Given a WGS84 point, the system SHALL return the showcase field that contains it, otherwise the grid cell that contains it, otherwise no unit.

#### Scenario: Point inside a showcase field
- **WHEN** a point lying inside a showcase field polygon is looked up
- **THEN** the field's unit is returned even though a grid cell also contains the point

#### Scenario: Point inside the grid but outside every field
- **WHEN** a point inside the national grid and outside every showcase field is looked up
- **THEN** the containing grid cell is returned

#### Scenario: Point outside all loaded bundles
- **WHEN** a point outside every loaded unit is looked up
- **THEN** no unit is returned

### Requirement: Optional tables
When a crop-history or suitability table is present it SHALL be validated under the same rules as the required tables. When either is absent the bundle SHALL still be valid and usable.

#### Scenario: Bundle without optional tables
- **WHEN** a bundle with no crop-history table and no suitability table is validated
- **THEN** validation succeeds

#### Scenario: Suitability index out of range
- **WHEN** a suitability table holds an index of 140
- **THEN** validation fails and the report states the allowed range of 0 to 100
