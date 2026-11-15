# Spec Delta

## Purpose

Turns scores and diagnostics into the five explanation elements required for each rotation strategy, traceable to named data sources and readable in Ukrainian or English.

## ADDED Requirements

### Requirement: Five explanation elements per strategy
Every returned strategy, including the baseline, SHALL carry five non-empty elements: why it was suggested, supporting evidence, expected benefits, information gaps and uncertainty, and risks requiring local review. For the baseline, the first element SHALL explain that it is the farmer's current rotation and the reference for comparison.

#### Scenario: Alternative has all five elements
- **WHEN** an alternative strategy is returned
- **THEN** each of the five elements contains at least one entry

#### Scenario: Baseline is explained as the reference
- **WHEN** the baseline strategy is returned
- **THEN** its first element states that it is the current rotation used as the reference and the other four elements are present

### Requirement: Reasons tied to priorities and trends
The reasons for an alternative SHALL name the farmer's highest-weighted priorities that the alternative improves relative to the baseline and any statistically significant site trend it responds to. A priority the farmer weighted zero SHALL NOT be given as a reason.

#### Scenario: Top priority is cited
- **WHEN** the farmer's highest priority is water conservation and an alternative improves the water score
- **THEN** the alternative's reasons cite water conservation and the size of the improvement

#### Scenario: Zero-weight priority is not cited
- **WHEN** the farmer set the forage priority to zero
- **THEN** no reason for any alternative cites forage value

#### Scenario: Significant trend is cited
- **WHEN** the site shows a significant decline in growing-season water balance and an alternative lowers water demand
- **THEN** the alternative's reasons cite that trend

### Requirement: Evidence records
Each evidence entry SHALL state the indicator, its value and unit, the source dataset, the period covered, the spatial resolution, and whether it describes the field, a grid cell, a climate cell or the rotation itself (values that come from crop traits and the rotation calendar and have no location). Every numeric statement in a strategy's reasons and benefits SHALL be backed by at least one evidence entry of that strategy.

#### Scenario: Evidence states source and resolution
- **WHEN** a strategy's evidence includes a bare-soil indicator derived from satellite data
- **THEN** the entry names the satellite product, the years covered and the resolution in meters

#### Scenario: Numeric claims are backed
- **WHEN** a benefit states a change in annual water demand
- **THEN** the strategy's evidence contains an entry for water demand with the same value

### Requirement: Benefits and trade-offs against the baseline
Expected benefits SHALL cover water, pest-cycle disruption, erosion control and soil health where the strategy changes them, with quantities where a physical unit is defined. Where a strategy is worse than the baseline on an objective, that trade-off SHALL be stated alongside the benefits.

#### Scenario: Quantified benefit
- **WHEN** an alternative reduces bare-soil days relative to the baseline
- **THEN** its benefits state the reduction in days per year

#### Scenario: Trade-off is disclosed
- **WHEN** an alternative with a cover crop has a higher annual water demand than the baseline
- **THEN** the increase is stated as a trade-off

### Requirement: Gaps reflect actual data conditions
The information-gap element SHALL always state the spatial resolution of the climate data, and SHALL additionally state each condition that applies: the satellite and soil values describe a grid cell and not the field; no satellite or soil data was available; soil properties were derived or assumed; a crop's traits are in draft status; no suitability data was available; snow cover is not modeled for winterkill.

#### Scenario: Grid-tier gap
- **WHEN** a strategy is produced in tier `grid`
- **THEN** its gaps state that satellite and soil values describe a cell of about 10 km and not the specific field

#### Scenario: Draft crop gap
- **WHEN** a strategy uses a crop whose knowledge-base status is draft
- **THEN** its gaps state that the crop's trait values are not yet reviewed and name the crop

#### Scenario: Gap that does not apply is absent
- **WHEN** a strategy is produced in tier `field` with supplied soil properties and only reviewed crops
- **THEN** its gaps contain no statement about grid cells, derived soil properties or draft crops

### Requirement: Local-review reminders
Every strategy SHALL state that the tool supports and does not replace the judgment of the farmer and a local agronomist, and that conditions it cannot observe, including land contamination, damage and current irrigation availability, must be checked locally. Condition-specific reminders SHALL be added when a strategy introduces a new crop, adds a cover crop, includes a winter crop, or grows a crop more often than its recommended return interval.

#### Scenario: Standing reminder is always present
- **WHEN** any strategy is returned
- **THEN** its local-review element includes the statement that the tool supports and does not replace farmer and agronomist judgment

#### Scenario: New crop reminder
- **WHEN** an alternative introduces a crop absent from the baseline
- **THEN** its local-review element includes a reminder to confirm market access, seed availability and equipment for that crop

#### Scenario: Cover crop reminder
- **WHEN** an alternative adds a cover crop
- **THEN** its local-review element includes a reminder to confirm termination timing and soil-moisture effects with a local agronomist

#### Scenario: Return-interval reminder
- **WHEN** a strategy grows a crop more often than its recommended return interval
- **THEN** its local-review element names the crop and the recommended interval and advises review of disease and soil-moisture risk

### Requirement: Ukrainian and English output
All explanation text SHALL be produced in the requested language, Ukrainian or English. The two renderings of one analysis SHALL contain the same entries and the same numbers.

#### Scenario: Language parity
- **WHEN** the same analysis is requested once in Ukrainian and once in English
- **THEN** both responses have the same number of entries in each element and identical numeric values

### Requirement: Reproducible wording
The same analysis inputs and data SHALL always produce the same explanation text.

#### Scenario: Repeated request
- **WHEN** an identical analysis is requested twice with unchanged data
- **THEN** the explanation text of every strategy is identical in both responses
