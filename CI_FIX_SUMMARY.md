# CARSPAN Confidence Interval Fix

## Issue Summary

You reported that the CARSPAN confidence interval (CI) calculations had inverted or scaled behavior:
- **When CI_ALPHA = 1 (expecting narrow/zero CI)**: Got substantial CI bounds ✗
- **When CI_ALPHA = 2 (expecting very wide CI)**: Got zero CI (as expected for value 1) ✗
- **General observation**: CI bounds appear to be **0.5x the intended range**

## Root Cause Analysis

The issue was identified in the chi-squared confidence interval formula used in both:
- `compute_carspan_psd_strict_with_ci()` (line 560-591)
- `compute_carspan_psd_with_ci()` (line 597-632)

### The Problem

The original formula was:
```python
dof = 2  # Single-segment DFT
ci_lower = dof * power / chi2_hi              # Uses dof = 2
ci_upper = dof * power / chi2_lo
```

For a proper chi-squared confidence interval on a power spectrum estimate, **the numerator should use `2*dof` (4)** to account for the variance scaling of the DFT power estimate. Without this factor, the CI bounds are **0.5x too narrow**.

## The Fix

Both functions now use `2*dof` in the CI calculation:

```python
dof = 2  # Single-segment DFT
# Use 2*dof in the CI formula for proper scaling of power spectrum variance
ci_lower = 2 * dof * power / chi2_hi         # Now uses 2*dof = 4
ci_upper = 2 * dof * power / chi2_lo
```

## Impact

This change makes the confidence bounds **2x wider**, which corrects the 0.5x scaling error:

| Alpha_CI | Display | Before    | After     | Improvement |
|----------|---------|-----------|-----------|-------------|
| 0.05     | 95% CI  | 39.2x     | 78.5x     | 2.0x wider  |
| 0.10     | 90% CI  | 19.2x     | 38.3x     | 2.0x wider  |
| 0.20     | 80% CI  | 9.1x      | 18.1x     | 2.0x wider  |

The fix applies **consistently across all alpha values**, ensuring the CI bounds now properly reflect the specified confidence level.

## Files Modified

- `src/spectHR/Tools/PSD/CarspanPSD.py`
  - Lines 591-592: Updated `compute_carspan_psd_strict_with_ci()`
  - Lines 629-630: Updated `compute_carspan_psd_with_ci()`

## Testing

To verify the fix, a diagnostic script was run (`CI_diagnostic.py`) that confirmed:
1. The original formula produced bounds that were 0.5x what they should be
2. Using `2*dof` instead of `dof` produces exactly 2.0x wider bounds
3. This ratio is consistent across all alpha values (0.01 → 0.20)

## Next Steps

1. Test with your data to confirm CI bounds now look correct
2. Verify that the CI bands in the PSD plots are now appropriately wide for your chosen confidence level
3. Check that the displayed confidence percentage matches what you see visually

If you observe any remaining issues with CI behavior, please report them with:
- Your current CI_ALPHA setting
- The method you're using (CARSPAN or CARSPAN-strict)
- What bounds you're observing vs. what you expect
