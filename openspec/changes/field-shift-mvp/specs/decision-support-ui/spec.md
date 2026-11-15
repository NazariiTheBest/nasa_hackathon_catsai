# Spec Delta

## Purpose

Gives a farmer a single-page, map-based workflow to describe a field, a current rotation and priorities, and to compare rotation strategies together with the reasoning and limits behind each one.

## ADDED Requirements

### Requirement: Location selection on a map
The user SHALL be able to choose a location by clicking a point on a map or by selecting a displayed showcase field. After a choice, the interface SHALL show which data tier is available for that location before any analysis is run.

#### Scenario: Clicking a point
- **WHEN** the user clicks a point on the map
- **THEN** a marker appears at the point and the interface shows the data tier available there

#### Scenario: Selecting a showcase field
- **WHEN** the user clicks a displayed showcase field
- **THEN** the field is highlighted and the interface shows that field-level data is available

### Requirement: Baseline rotation entry
The user SHALL be able to build the current rotation as an ordered list of crops chosen from the catalog, to add, remove and reorder entries, and to attach cover crops. The interface SHALL NOT allow an analysis to be started with an empty rotation.

#### Scenario: Building a rotation
- **WHEN** the user adds winter wheat and sunflower and then moves sunflower first
- **THEN** the rotation shows sunflower followed by winter wheat

#### Scenario: Empty rotation blocks analysis
- **WHEN** the rotation list is empty
- **THEN** the control that starts the analysis is disabled and the reason is shown

### Requirement: Priorities and constraints entry
The user SHALL be able to set a priority level for water conservation, nitrogen fixation, erosion reduction, organic matter, forage value and market income, and to state whether irrigation is available, which crops to exclude and the longest acceptable rotation.

#### Scenario: Priorities are sent with the analysis
- **WHEN** the user raises water conservation to its maximum, leaves forage at zero and starts the analysis
- **THEN** the analysis request carries those priority values

#### Scenario: Excluding a crop
- **WHEN** the user excludes soybean and runs the analysis
- **THEN** no displayed alternative introduces soybean

### Requirement: Site diagnosis view
After an analysis, the interface SHALL show the site's bare-soil windows on a calendar timeline, the stress calendar by crop and hazard, and the long-term trends with an indication of which are statistically significant.

#### Scenario: Diagnosis is displayed
- **WHEN** an analysis completes
- **THEN** the bare-soil windows, the stress calendar and the trends are visible with their values

#### Scenario: Insignificant trend is distinguishable
- **WHEN** a displayed trend is not statistically significant
- **THEN** it is visually distinguished from significant trends and labeled as not significant

### Requirement: Strategy comparison
The interface SHALL present the baseline and every alternative side by side, each with its crop sequence on a calendar, its overall score with the uncertainty interval, its confidence level, and its objective scores shown against the baseline's.

#### Scenario: At least three strategies compared
- **WHEN** an analysis returns a baseline and two or more alternatives
- **THEN** all returned strategies are visible together with scores, intervals and confidence levels, and the baseline is labeled as such

#### Scenario: Interval accompanies every score
- **WHEN** an overall score is displayed
- **THEN** its uncertainty interval is displayed with it

### Requirement: Explanation detail
For each strategy, the user SHALL be able to read why it was suggested, the supporting evidence with source and resolution, the expected benefits and trade-offs, the information gaps and the risks requiring local review. The gaps and local-review items SHALL be reachable with no more than one interaction from the comparison view.

#### Scenario: Opening a strategy
- **WHEN** the user opens a strategy from the comparison view
- **THEN** all five explanation elements are shown, and each evidence entry displays its source, period and resolution

### Requirement: Language switch
The user SHALL be able to switch the interface between Ukrainian and English at any time. Interface labels SHALL change immediately, and analysis text SHALL be shown in the selected language.

#### Scenario: Switching language after an analysis
- **WHEN** the user switches from English to Ukrainian while results are displayed
- **THEN** interface labels, crop names and explanation text are shown in Ukrainian with the same numbers as before

### Requirement: Loading and error states
While an analysis is running, the interface SHALL show that it is in progress and prevent duplicate submissions. When an analysis fails, the interface SHALL show the cause in plain language with a way to retry, and SHALL NOT present results of an earlier analysis as the result of the failed one.

#### Scenario: Analysis in progress
- **WHEN** the user starts an analysis
- **THEN** a progress indication is shown and the start control is disabled until the analysis finishes

#### Scenario: Climate data unavailable
- **WHEN** an analysis fails because climate data is unavailable
- **THEN** a message explains that climate data could not be reached and offers a retry, and no earlier results are shown as current

### Requirement: Satellite context layer
The map SHALL offer a NASA satellite vegetation layer that the user can switch on and off. A failure to load that layer SHALL NOT prevent location selection or analysis.

#### Scenario: Toggling the layer
- **WHEN** the user switches the vegetation layer on
- **THEN** NASA vegetation imagery is drawn over the base map with attribution

#### Scenario: Layer fails to load
- **WHEN** the vegetation layer cannot be loaded
- **THEN** the base map, location selection and analysis continue to work
