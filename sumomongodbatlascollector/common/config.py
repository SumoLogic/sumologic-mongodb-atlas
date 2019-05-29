# -*- coding: future_fstrings -*-
import os
from sumoclient.utils import get_logger
import yaml

log = get_logger(__name__)


class Config(object):

    def get_config(self, config_filename, root_dir, input_cfgpath=''):
        ''' reads base config and merges with user config'''
        base_config_path = os.path.join(root_dir, config_filename)
        base_config = self.read_config(base_config_path)

        cfg_locations = self.get_config_locations(input_cfgpath, config_filename)
        usercfg = self.get_user_config(cfg_locations)
        if not usercfg:
            usercfg = self.get_config_from_env(base_config)
        log.info(f'''usercfg: {usercfg}''')
        self.config = self.merge_config(base_config, usercfg)
        self.validate_config(self.config)
        log.info(f"config object created")
        return self.config

    def validate_config(self, config):
        has_all_params = True
        for section, section_cfg in config.items():
            for k, v in section_cfg.items():
                if v is None:
                    log.info(f"Missing parameter {k} from config")
                    has_all_params = False
        if not has_all_params:
            raise Exception("Invalid config")

    def get_config_from_env(self, base_config):
        log.info("fetching parameters from environment")
        cfg = {}
        for section, section_cfg in base_config.items():
            new_section_cfg = {}
            for k, v in section_cfg.items():
                if k in os.environ:
                    new_section_cfg[k] = os.environ[k]
                else:
                    new_section_cfg[k] = v
            cfg[section] = new_section_cfg
        return cfg


    def get_config_locations(self, input_cfgpath, config_filename):
        home_dir = os.path.join(os.path.expanduser("~"), config_filename)
        cfg_locations = [input_cfgpath, home_dir, os.getenv("SUMO_API_COLLECTOR_CONF", '')]
        return cfg_locations

    def get_user_config(self, cfg_locations):
        usercfg = {}
        for filepath in cfg_locations:
            if os.path.isfile(filepath):
                usercfg = self.read_config(filepath)
                break
        return usercfg

    def merge_config(self, base_config, usercfg):
        for k, v in usercfg.items():
            if k in base_config:
                base_config[k].update(v)
            else:
                base_config[k] = v
        return base_config


    @classmethod
    def read_config(cls, filepath):
        log.info(f"Reading config file: {filepath}")
        config = {}
        with open(filepath, 'r') as stream:
            try:
                config = yaml.load(stream)
            except yaml.YAMLError as exc:
                log.error(f"Unable to read config {filepath} Error: {exc}")
        return config
