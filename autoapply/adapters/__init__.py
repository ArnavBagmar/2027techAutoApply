from autoapply.adapters.base import ADAPTERS
from autoapply.adapters.greenhouse import GreenhouseAdapter
from autoapply.adapters.lever import LeverAdapter

ADAPTERS.append(GreenhouseAdapter())
ADAPTERS.append(LeverAdapter())
