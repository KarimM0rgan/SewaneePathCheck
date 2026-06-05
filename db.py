# CS284 Final Project
# Safae Berhenich & Karim Morgan

import MySQLdb

DB_CONFIG = {
    "host":   "warren.sewanee.edu",
    "user":   "xxx",
    "passwd": "xxx",
    "db":     "xxx",
}

def get_db():
    return MySQLdb.connect(**DB_CONFIG)
