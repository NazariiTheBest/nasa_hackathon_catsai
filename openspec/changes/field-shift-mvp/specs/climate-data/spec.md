# Spec Delta

## Purpose

Provides multi-decade daily climate series from NASA POWER for any location, cached so that analyses stay fast and keep working when the network or the source is unavailable.

## ADDED Requirements

### Requirement: Daily climate series for a point
For any WGS84 point, the system SHALL provide daily series of minimum, maximum and mean air temperature, dew point, relative humidity, wind speed, precipitation, incoming solar radiation, and surface and root-zone soil wetness from NASA POWER. The series SHALL cover at least 30 complete calendar years and end with the most recent complete calendar year.

#### Scenario: Series is returned for a point in Ukraine
- **WHEN** a climate series is requested for a point in Ukraine
- **THEN** a daily series containing all listed variables for at least 30 complete calendar years is returned

#### Scenario: Partial current year is excluded
- **WHEN** a series is requested partway through a calendar year
- **THEN** the returned series ends on 31 December of the previous year

### Requirement: Missing values are explicit
Values that the source marks as missing SHALL be represented as missing and SHALL NOT enter any calculation as numbers.

#### Scenario: Source fill value becomes missing
- **WHEN** the source returns its fill value for solar radiation on a given day
- **THEN** that day's solar radiation is missing in the returned series

### Requirement: Persistent cache per source grid cell
The system SHALL store each retrieved series persistently, keyed by the source's grid cell, and SHALL serve any later request falling in the same cell from the stored series without contacting the source.

#### Scenario: Repeated request makes no network call
- **WHEN** a series is requested twice for the same point
- **THEN** the second request is served without contacting the source

#### Scenario: Nearby point shares the cached cell
- **WHEN** a series is requested for a point that lies in the same source grid cell as a previously requested point
- **THEN** the request is served from the stored series

#### Scenario: Cache survives a restart
- **WHEN** the system is restarted after a series was retrieved
- **THEN** a request for the same cell is served without contacting the source

### Requirement: Defined behavior when the source is unreachable
When NASA POWER cannot be reached, the system SHALL serve a stored series if one exists for the cell, and SHALL otherwise report that climate data is unavailable. It SHALL NOT return partial, interpolated-from-nothing or synthetic climate data.

#### Scenario: Source down with stored series
- **WHEN** the source is unreachable and the requested cell is stored
- **THEN** the stored series is returned

#### Scenario: Source down without stored series
- **WHEN** the source is unreachable and the requested cell is not stored
- **THEN** a climate-unavailable error is reported and no series is returned

### Requirement: Resumable cache pre-warming
An operator SHALL be able to pre-fetch climate series for a list of locations in one operation. The operation SHALL skip cells already stored, continue past individual failures, and report how many cells were fetched, skipped and failed.

#### Scenario: Interrupted pre-warm is resumed
- **WHEN** a pre-warm over 300 cells is interrupted after 120 cells and run again
- **THEN** the second run fetches only the remaining cells

#### Scenario: Individual failure does not stop the run
- **WHEN** one cell fails to download during a pre-warm
- **THEN** the remaining cells are still processed and the failed cell is listed in the summary

### Requirement: Series provenance
Every series SHALL carry the source name, its spatial resolution, the period covered and the retrieval date, so that evidence derived from it can state where it came from.

#### Scenario: Provenance accompanies a series
- **WHEN** a series is returned
- **THEN** it includes the source name, spatial resolution, first and last date and retrieval date
