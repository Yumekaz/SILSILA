import warnings

from requests.exceptions import RequestsDependencyWarning


# Keep smoke-test output clean from environment-specific dependency noise.
warnings.filterwarnings("ignore", category=RequestsDependencyWarning)
warnings.filterwarnings(
    "ignore",
    message="ast.NameConstant is deprecated and will be removed in Python 3.14; use ast.Constant instead",
    category=DeprecationWarning,
)
