import config

def set_memory_list():
    config.memory_list = []

def append_element(x):
    config.memory_list.append(x)

def get_memory_list():
    return config.memory_list

def get_memory_count():
    return len(config.memory_list)
    