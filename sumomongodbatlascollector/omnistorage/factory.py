# -*- coding: future_fstrings -*-
from common.mixin import DynamicLoadMixin


class ProviderFactory(DynamicLoadMixin):

    provider_map = {
        # "aws": AWSProvider,
        # "azure": AzureProvider,
        "gcp": "gcp.GCPProvider",
        "onprem": "onprem.OnPremProvider"
    }

    @classmethod
    def get_provider(cls, provider_name, *args, **kwargs):

        if provider_name in cls.provider_map:
            module_class = cls.load_class(cls.provider_map[provider_name], __name__)
            module_instance = module_class(*args, **kwargs)
            return module_instance
        else:
            raise Exception(f"{provider_name} provider not found")

    @classmethod
    def add_provider(cls, provider_name, provider_class):
        cls.provider_map[provider_name] = provider_class


