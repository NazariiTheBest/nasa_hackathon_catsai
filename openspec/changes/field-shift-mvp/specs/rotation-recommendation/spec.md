# Spec Delta

## Purpose

Generates feasible alternative crop rotations from a farmer's baseline and ranks them against the farmer's priorities under historical weather, with a stated uncertainty and confidence for each.

## ADDED Requirements

### Requirement: Rotation calendar from a crop sequence
Given an ordered list of crops and optional cover crops, the system SHALL build a dated rotation calendar with a sowing and a harvest date for each crop, using knowledge-base sowing windows and growth lengths. A baseline SHALL NOT be rejected because its declared order conflicts with knowledge-base timing; the dates SHALL be adjusted and a notice attached.

#### Scenario: Winter crop spans two calendar years
- **WHEN** a sequence containing winter wheat is turned into a calendar
- **THEN** the wheat's sowing falls in autumn of one cycle year and its harvest in summer of the next

#### Scenario: Tight baseline timing produces a notice
- **WHEN** a declared baseline places a winter crop after a crop whose typical harvest is later than the winter crop's sowing window
- **THEN** the baseline is still evaluated and a notice describes the timing conflict

### Requirement: Alternatives derived by named operators
Alternative rotations SHALL be derived from the baseline by these operators, alone or combined: inserting a cover crop into a bare-soil window, substituting a more drought-tolerant crop, adding a legume, diversifying crop families, and extending the cycle. Each alternative SHALL record the operators that produced it.

#### Scenario: Cover crop fills a long bare window
- **WHEN** the baseline has a bare-soil window of at least 60 days that fits a cover crop's sowing window
- **THEN** at least one generated alternative places a cover crop in that window

#### Scenario: Operators are recorded
- **WHEN** an alternative is returned
- **THEN** it lists the operators applied to the baseline to obtain it

### Requirement: Hard agronomic and user constraints
No returned alternative SHALL violate a sowing window, introduce a crop whose heat requirement the site meets in fewer than 80% of historical years, introduce a crop the user excluded, exceed the user's maximum cycle length, or introduce an irrigation-dependent crop when the user reports no irrigation. An alternative SHALL NOT introduce a crop, or grow a baseline crop more often, in a way that breaks that crop's or family's minimum return interval.

#### Scenario: Introduced crop respects its return interval
- **WHEN** an alternative introduces a crop with a minimum return interval of 4 years
- **THEN** that crop appears at most once in any 4-year span of the alternative's repeated cycle

#### Scenario: Baseline frequency is never increased
- **WHEN** the baseline grows sunflower every second year, more often than its minimum return interval allows
- **THEN** returned alternatives may keep or reduce that frequency, none grows sunflower more often, and each alternative that keeps it is marked as retaining a return-interval violation

#### Scenario: Excluded crop never appears
- **WHEN** the user excludes soybean
- **THEN** no returned alternative introduces soybean

#### Scenario: Irrigation-dependent crop without irrigation
- **WHEN** the user reports that irrigation is unavailable
- **THEN** no returned alternative introduces a crop flagged as irrigation-dependent

### Requirement: Suitability screening
When a suitability table exists for the unit, the system SHALL NOT introduce a crop whose suitability index is below the configured floor. When no suitability data exists, no screening SHALL be applied and the absence SHALL be recorded for the explanation.

#### Scenario: Unsuitable crop is not introduced
- **WHEN** a unit's suitability index for sorghum is below the floor
- **THEN** no returned alternative introduces sorghum on that unit

#### Scenario: No suitability data
- **WHEN** a site has no suitability table
- **THEN** alternatives are generated without suitability screening and the absence is recorded

### Requirement: Objective scores
Each strategy SHALL receive a score between 0 and 1, where higher is better, for water, nitrogen, erosion, organic matter, forage, income, climate resilience and pest-cycle break. Identical inputs SHALL produce identical scores.

#### Scenario: Scores are reproducible
- **WHEN** the same analysis is run twice with unchanged data
- **THEN** every objective score is identical between the two runs

#### Scenario: Legume raises the nitrogen score
- **WHEN** an alternative differs from the baseline only by replacing a non-legume with a legume
- **THEN** its nitrogen score is higher than the baseline's

#### Scenario: Cover crop lowers bare-soil exposure
- **WHEN** an alternative differs from the baseline only by a cover crop placed in a bare-soil window
- **THEN** its erosion score is not lower than the baseline's

### Requirement: Cover crop water cost
The water objective SHALL include the water used by cover crops, so that inserting a cover crop can lower a strategy's water score.

#### Scenario: Cover crop water use is counted
- **WHEN** an alternative adds a cover crop to the baseline
- **THEN** the strategy's reported annual water demand is higher than the baseline's by the cover crop's use

### Requirement: Priority-weighted overall score
The overall score SHALL combine the six farmer-weighted objectives (water, nitrogen, erosion, organic matter, forage, income) in proportion to the farmer's priorities, with a fixed share reserved for climate resilience and pest-cycle break. When every priority is zero, equal weights SHALL be used and a notice attached.

#### Scenario: Priorities change the overall score only
- **WHEN** two analyses differ only in the farmer's priorities
- **THEN** each strategy's objective scores are identical in both and its overall score differs

#### Scenario: All priorities zero
- **WHEN** an analysis is requested with every priority set to zero
- **THEN** equal weights are used and the response carries a notice saying so

### Requirement: Historical weather replay and uncertainty
Each strategy SHALL be evaluated against every available historical weather window of the cycle's length. Its overall score SHALL be reported as a median with a 10th-to-90th percentile interval and the number of windows evaluated.

#### Scenario: Interval accompanies the score
- **WHEN** a strategy with a 3-year cycle is evaluated on 40 years of climate data
- **THEN** its overall score is reported as a median, a 10th and a 90th percentile and a count of 38 windows

### Requirement: Strategy selection
The result SHALL contain the baseline, flagged as such, and at least two alternatives whenever at least two feasible alternatives exist. No two returned strategies SHALL have the same crop sequence. When fewer than two feasible alternatives exist, those that exist SHALL be returned with a notice stating which constraints eliminated the rest.

#### Scenario: Baseline plus alternatives
- **WHEN** an analysis yields many feasible alternatives
- **THEN** the result contains the flagged baseline and at least two alternatives with mutually different crop sequences

#### Scenario: Over-constrained request
- **WHEN** the user's constraints leave only one feasible alternative
- **THEN** the baseline and that alternative are returned with a notice naming the limiting constraints

### Requirement: Comparison against the baseline
Each alternative SHALL report its difference from the baseline for every objective score and, in physical units, for annual water demand, bare-soil days per year and nitrogen fixed per hectare per year.

#### Scenario: Physical deltas are reported
- **WHEN** an alternative is returned
- **THEN** it states its change in annual water demand in millimeters, in bare-soil days per year and in nitrogen fixed per hectare per year relative to the baseline

### Requirement: Confidence level
Each strategy SHALL carry a confidence level of `high`, `medium` or `low` that decreases with coarser data tier, wider score interval, use of draft knowledge-base crops and use of derived or assumed inputs. A strategy in tier `climate_only` SHALL be `low`, and a strategy in tier `grid` SHALL NOT be `high`.

#### Scenario: Climate-only analysis
- **WHEN** a strategy is produced in tier `climate_only`
- **THEN** its confidence level is `low`

#### Scenario: Grid-tier analysis
- **WHEN** a strategy is produced in tier `grid`
- **THEN** its confidence level is `medium` or `low`
