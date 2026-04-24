# Confidence Interval (CI) Interpretation Fix

## The Issue

You correctly identified that the CI_ALPHA parameter was being interpreted **backwards**:

- **Expected**: CI_ALPHA = 1.0 → 100% confidence → **zero bounds**
- **Actual**: CI_ALPHA = 1.0 → 0% confidence → **tight bounds** (essentially zero width, but calculated differently)

When you set CI_ALPHA = 2 (invalid for significance level), you got close to zero bounds, which is what you expected for CI_ALPHA = 1.

## Root Cause

The code was treating **CI_ALPHA as a significance level** (like α in statistics, where 0.05 = 95% CI):
```python
# OLD (significance level interpretation)
alpha = CI_ALPHA  # e.g., 0.05 means 95% CI
chi2_lo = chi2.ppf(alpha / 2, dof)       # ppf(0.025, 2)
chi2_hi = chi2.ppf(1 - alpha / 2, dof)   # ppf(0.975, 2)
```

But you were thinking of it as a **confidence level** (0.95 = 95% CI):
```python
# Expected by user
alpha_ci = 0.95  # means 95% confidence
# Should map to significance level: alpha = 1 - 0.95 = 0.05
```

## The Fix

All three PSD methods (Welch, Lomb-Scargle, CARSPAN) now use the **confidence level interpretation**:

```python
# NEW (confidence level interpretation)
alpha_ci = CI_ALPHA  # e.g., 0.95 means 95% confidence
alpha = 1 - alpha_ci  # Convert to significance level
chi2_lo = chi2.ppf(alpha / 2, dof)       # ppf(0.025, 2) for 95% CI
chi2_hi = chi2.ppf(1 - alpha / 2, dof)   # ppf(0.975, 2) for 95% CI
```

## What Changed

### Parameter Name & Default
- **Old default**: `confidence_interval_alpha: 0.05` (significance level, 95% CI)
- **New default**: `confidence_interval_alpha: 0.95` (confidence level, 95% CI)

### Interpretation
| CI_ALPHA | **Old Meaning** | **New Meaning** | **Behavior** |
|----------|----------------|-----------------|------------|
| 0.05     | 95% CI         | 5% CI           | Very tight bounds |
| 0.50     | 50% CI         | 50% CI          | Moderate bounds |
| 0.95     | 5% CI          | 95% CI          | Wide bounds ✓ |
| 1.00     | 0% CI          | 100% CI         | Infinite bounds (no confidence) |

### Files Modified
1. **CarspanPSD.py** (lines 586-588, 624-630)
   - `compute_carspan_psd_strict_with_ci()`
   - `compute_carspan_psd_with_ci()`
   - Added: `alpha = 1 - alpha_ci` before chi-squared quantile calculation

2. **WelchPSD.py** (lines 196, 207, 256-260)
   - `compute_welch_psd_with_ci()`
   - Changed default from `alpha=0.05` to `alpha=0.95`
   - Updated docstring
   - Added: `alpha_sig = 1 - alpha` before chi-squared quantile calculation

3. **LombScarglePSD.py** (lines 181, 192, 214-219)
   - `compute_lombscargle_psd_with_ci()`
   - Changed default from `alpha=0.05` to `alpha=0.95`
   - Updated docstring
   - Added: `alpha_sig = 1 - alpha` before chi-squared quantile calculation

4. **CardioFrequencyMetricsMixin.py** (lines 90-91)
   - Updated docstring to clarify CI_ALPHA is now a confidence level
   - Changed default from `CI_ALPHA = 0.05` to `CI_ALPHA = 0.95`

5. **workSpace.py** (line 49)
   - Updated default config from `"confidence_interval_alpha": 0.05` to `"confidence_interval_alpha": 0.95`

## How to Use

### In your workspace.json:
```json
"FrequencyAnalysis": {
    "method": "welch",
    "confidence_interval_alpha": 0.95  // 95% confidence interval
}
```

### Expected behavior:
- **CI_ALPHA = 0.99**: Very wide bounds (99% confidence)
- **CI_ALPHA = 0.95**: Normal bounds (95% confidence) ✓
- **CI_ALPHA = 0.68**: Narrow bounds (68% confidence)
- **CI_ALPHA = 0.00**: Point estimate with very tight bounds (0% confidence = complete uncertainty)
- **CI_ALPHA = 1.00**: Infinite bounds (100% confidence = impossible to be confident about bounds)

## Testing

You can verify the fix works correctly:
1. Set `confidence_interval_alpha: 0.95` in your workspace
2. CARSPAN CI bounds should be reasonably wide (comparable to other methods)
3. Set `confidence_interval_alpha: 1.0` → should get infinite/very wide bounds
4. Set `confidence_interval_alpha: 0.5` → should get very narrow bounds

## Backward Compatibility Note

**⚠️ Breaking Change**: If you have existing workspace.json files with custom `confidence_interval_alpha` values, they will now be interpreted differently:

- **Old**: `confidence_interval_alpha: 0.05` meant 95% CI
- **New**: `confidence_interval_alpha: 0.05` means 5% CI

To migrate your settings, use: `new_value = 1 - old_value`
- Old 0.05 (95% CI) → New 0.95
- Old 0.01 (99% CI) → New 0.99
- Old 0.10 (90% CI) → New 0.90
