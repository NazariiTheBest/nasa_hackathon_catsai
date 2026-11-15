# Spec Delta

## Purpose

Exposes location lookup, the crop catalog, showcase areas and rotation analysis to client applications through a documented HTTP interface with predictable validation and error reporting.

## ADDED Requirements

### Requirement: Analysis request
The API SHALL accept one analysis request containing a location, a baseline rotation, farmer priorities, constraints and a language, and SHALL return the site diagnosis, the strategies with their explanations and response metadata in a single response. The location SHALL be accepted as a point, a unit identifier or a polygon.

#### Scenario: Point request
- **WHEN** a valid analysis request with a point location in Ukraine is submitted
- **THEN** the response has a success status and contains a site diagnosis and at least three strategies, one of them flagged as the baseline

#### Scenario: Unit request
- **WHEN** a valid analysis request names a showcase field by its unit identifier
- **THEN** the analysis is produced for that field in tier `field`

#### Scenario: Polygon request
- **WHEN** a valid analysis request supplies a polygon
- **THEN** the analysis is produced for the polygon's centroid and a notice in the response says so

### Requirement: Input validation
The API SHALL reject an invalid request with a client-error status and a message for each invalid field. Invalid inputs include a latitude or longitude out of range, an unknown crop identifier, an empty baseline, a priority outside 0 to 1, an unknown unit identifier and an unsupported language.

#### Scenario: Unknown crop identifier
- **WHEN** an analysis request lists a crop identifier that is not in the catalog
- **THEN** the response has a client-error status and names the unknown identifier

#### Scenario: Several invalid fields
- **WHEN** an analysis request has a latitude of 120 and an empty baseline
- **THEN** the response has a client-error status and reports both problems

#### Scenario: Unsupported language
- **WHEN** an analysis request asks for a language other than Ukrainian or English
- **THEN** the response has a client-error status and lists the supported languages

### Requirement: Location lookup endpoint
The API SHALL return, for a point, the data tier and a summary of the unit that contains it, without running an analysis.

#### Scenario: Point in a grid cell
- **WHEN** a lookup is requested for a point inside the national grid and outside every showcase field
- **THEN** the response reports tier `grid` and the cell's identifier

#### Scenario: Point outside all bundles
- **WHEN** a lookup is requested for a point outside every loaded unit
- **THEN** the response reports tier `climate_only` and no unit

### Requirement: Crop catalog endpoint
The API SHALL return the crop catalog with each crop's identifier, name in the requested language, role, family, season type and review status.

#### Scenario: Catalog in Ukrainian
- **WHEN** the catalog is requested in Ukrainian
- **THEN** every crop is returned with its Ukrainian name, role, family, season type and review status

### Requirement: Showcase areas endpoint
The API SHALL return the showcase areas with the geometry and identifier of each showcase field in a form a map client can display directly.

#### Scenario: Showcase fields are listed
- **WHEN** the showcase areas are requested and a field bundle is loaded
- **THEN** the response contains each field's identifier, name and polygon geometry in WGS84

#### Scenario: No field bundle loaded
- **WHEN** the showcase areas are requested and no field bundle is loaded
- **THEN** the response is an empty collection with a success status

### Requirement: Response metadata
Every analysis response SHALL include the contract version, the engine version, the data tier, the time of generation and a list of notices describing any adjustment the system made to the request or its interpretation.

#### Scenario: Metadata is present
- **WHEN** an analysis response is returned
- **THEN** it includes contract version, engine version, data tier, generation time and a notices list that may be empty

### Requirement: Upstream failure reporting
When climate data cannot be obtained for an analysis, the API SHALL respond with a service-unavailable status and a machine-readable code identifying the cause. It SHALL NOT return an analysis computed from incomplete inputs as if it were complete.

#### Scenario: Climate source unreachable and nothing cached
- **WHEN** an analysis is requested for a location whose climate cell is not stored while the climate source is unreachable
- **THEN** the response has a service-unavailable status with the code `climate_unavailable` and contains no strategies

### Requirement: Published machine-readable schema
The API SHALL publish a machine-readable description of every endpoint, request and response, and actual responses SHALL conform to it.

#### Scenario: Response conforms to the published schema
- **WHEN** an analysis response is checked against the published schema
- **THEN** it validates without errors

### Requirement: Analysis response time
With the location's climate series already stored, an analysis SHALL complete within 10 seconds on the development laptop.

#### Scenario: Warm analysis
- **WHEN** an analysis is requested for a location whose climate cell is stored
- **THEN** the response is returned within 10 seconds

### Requirement: Health endpoint
The API SHALL report its readiness, including which bundles are loaded with their unit counts, how many crops the knowledge base holds and how many climate cells are stored.

#### Scenario: Health after start-up
- **WHEN** the health endpoint is requested after start-up
- **THEN** the response lists the loaded bundles with unit counts, the crop count and the number of stored climate cells
