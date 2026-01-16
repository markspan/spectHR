# spectHR/Actions/ibiClassify.py
import warnings


def ibiClassify(target, **kwargs):
    warnings.warn(
        "ibiClassify is deprecated; use CardioSeries.classify_ibi()",
        DeprecationWarning,
        stacklevel=2,
    )
    target.classify_ibi(**kwargs)
