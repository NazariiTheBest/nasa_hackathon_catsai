# Spec Delta

## Purpose

Holds the agronomic traits of every crop the tool can reason about, with sources and a review status, so that recommendations are traceable and can be tuned by an agronomist without changing code.

## ADDED Requirements

### Requirement: Crop trait record
Each crop SHALL have an identifier, names in Ukrainian and English, botanical family, role, season type, sowing window, base temperature, heat units to maturity, growth-stage lengths, crop coefficients, rooting depth, stress thresholds, drought tolerance, nitrogen fixation, residue cover, forage value, market value, minimum return interval and an irrigation-dependence flag.

#### Scenario: Complete record loads
- **WHEN** the knowledge base contains a crop with every required trait
- **THEN** the crop is available to the rest of the system

#### Scenario: Missing trait blocks loading
- **WHEN** a crop record lacks its rooting depth
- **THEN** loading fails and the error names the crop and the missing trait

### Requirement: Trait value validation
Trait values SHALL be checked on load: day-of-year values between 1 and 366, crop coefficients between 0 and 1.5, index-type traits between 0 and 1, a minimum return interval of at least 1 year, and a sowing window whose start precedes its end within the crop's season.

#### Scenario: Out-of-range coefficient is rejected
- **WHEN** a crop declares a mid-season crop coefficient of 3.0
- **THEN** loading fails and the error names the crop, the trait and the allowed range

#### Scenario: Duplicate crop identifier is rejected
- **WHEN** two crop records share an identifier
- **THEN** loading fails and the error names the duplicated identifier

### Requirement: Provenance and review status
Every crop SHALL list at least one source for its trait values and SHALL carry a review status of `draft` or `reviewed`. The review status SHALL be visible wherever the crop catalog is exposed.

#### Scenario: Crop without a source is rejected
- **WHEN** a crop record has an empty source list
- **THEN** loading fails and the error names the crop

#### Scenario: Review status is exposed
- **WHEN** the crop catalog is listed
- **THEN** each crop shows whether it is draft or reviewed

### Requirement: Editable without code changes
The knowledge base and the non-crop engine thresholds SHALL be plain data files that an agronomist can edit. Edited values SHALL take effect the next time the system starts, with no change to program code.

#### Scenario: Edited threshold changes the analysis
- **WHEN** an agronomist lowers a crop's heat-stress temperature in the knowledge base and the system is restarted
- **THEN** the next analysis for that crop reports a heat-stress probability computed with the new temperature

### Requirement: Coverage of Ukraine-relevant crops
The knowledge base SHALL contain at least 15 crops grown or growable in Ukraine, including at least 3 cover crops, at least 3 legumes, at least 2 winter cash crops, at least 2 spring-sown cash crops and at least 2 crops classed as drought-tolerant alternatives.

#### Scenario: Catalog meets coverage minimums
- **WHEN** the shipped knowledge base is loaded
- **THEN** it contains at least 15 crops and meets each of the stated minimums by role and type

### Requirement: Localized crop names
The crop catalog SHALL return crop names in the requested language, Ukrainian or English.

#### Scenario: Ukrainian catalog
- **WHEN** the catalog is requested in Ukrainian
- **THEN** every crop name is returned in Ukrainian

#### Scenario: English catalog
- **WHEN** the catalog is requested in English
- **THEN** every crop name is returned in English
