"""Migrate singles tables to new HisparcSingle format.

HisparcSingle columns where `tables.UInt16Col` before
HiSPARC/datastore@dec64079. Convert old tables to the new format.
For a missing secondary (two detector stations) the secondary columns where set
to all zero, instead of all `-1`. Set those columns to `-1`

logging to logfile `migration.log`
prints progressbars for searching and processing tables.

"""

import glob
import logging
import re

import numpy as np
import tables

from sapphire import HiSPARCNetwork
from sapphire.utils import pbar

DATASTORE_PATH = '/data/hisparc/tom/Datastore/frome/'
# DATASTORE_PATH = '/databases/frome/'


class MigrateSingles:
    """Migrate singles to new table format
    If the station has no secondary *and* secondary columns are all zero,
    replace secondary columns with `-1` to correctly represent missing secondary.
    """

    class HisparcSingle(tables.IsDescription):
        event_id = tables.UInt32Col(pos=0)
        timestamp = tables.Time32Col(pos=1)
        mas_ch1_low = tables.Int32Col(dflt=-1, pos=2)
        mas_ch1_high = tables.Int32Col(dflt=-1, pos=3)
        mas_ch2_low = tables.Int32Col(dflt=-1, pos=4)
        mas_ch2_high = tables.Int32Col(dflt=-1, pos=5)
        slv_ch1_low = tables.Int32Col(dflt=-1, pos=6)
        slv_ch1_high = tables.Int32Col(dflt=-1, pos=7)
        slv_ch2_low = tables.Int32Col(dflt=-1, pos=8)
        slv_ch2_high = tables.Int32Col(dflt=-1, pos=9)

    def __init__(self, data):
        self.data = data
        self.singles_dtype = tables.description.dtype_from_descr(self.HisparcSingle)
        self.network = HiSPARCNetwork(force_stale=True)

    def migrate_table(self, table_path):
        """Migrate datatable to new format. Fix secondary columns."""

        logging.info(f'Migrating table: {table_path}')
        group, table_name, sn = self._parse_path(table_path)

        if table_name != 'singles':
            logging.error(f'Table {table_path} not `singles` skipping!')
            return None

        tmp_table_name = f'_t_{table_name}'

        try:
            tmptable = self.data.create_table(group, tmp_table_name, description=self.HisparcSingle)
        except tables.NodeError:
            logging.exception(f'{group}/_t_{table_name} exists. Removing.')
            self.data.remove_node(group, f'_t_{table_name}')
            tmptable = self.data.create_table(group, tmp_table_name, description=self.HisparcSingle)

        table = self.data.get_node(table_path)
        data = table.read()
        data = data.astype(self.singles_dtype)
        if not self._has_secondary(sn):
            data = self._mark_secondary_columns_as_missing(data)

        tmptable.append(data)
        tmptable.flush()
        self.data.rename_node(table, 'singles_old')
        self.data.rename_node(tmptable, 'singles')

    def _parse_path(self, path):
        """'/cluster/s501/singles' ---> '/cluster/s501' 'singles', 501"""

        group, table_name = tables.path.split_path(path)
        re_number = re.compile('[0-9]+$')
        numbers = [int(re_number.search(group).group())]
        sn = numbers[-1]
        return group, table_name, sn

    def _has_secondary(self, sn):
        """Return True if station (sn) has secondary (4 detectors)"""
        try:
            n_detectors = len(self.network.get_station(sn).detectors)
        except AttributeError:
            logging.exception(f'No information in HiSPARCNetwork() for sn {sn}')
            n_detectors = 4
        return n_detectors == 4

    def _mark_secondary_columns_as_missing(self, table):
        """Replace secondary columns with `-1`"""

        cols = ['slv_ch1_low', 'slv_ch2_low', 'slv_ch1_high', 'slv_ch2_high']
        for col in cols:
            if not np.all(table[col] == 0):
                logging.error('Secondary columns are not all zero. Leaving data untouched!')
                return table

        n = len(table)
        for col in cols:
            table[col] = n * [-1]

        logging.debug('Set all secondary columns to `-1`.')
        return table


def get_queue(datastore_path):
    queue = {}
    logging.info('Searching for unmigrated singles tables')

    print('Looking for singles tables in datastore.')

    # Singles tables were added in Feb, 2016.
    for fn in pbar(glob.glob(datastore_path + '/201[6,7]/*/*h5')):
        singles_tables = []
        with tables.open_file(fn, 'r') as data:
            for node in data.walk_nodes('/', 'Table'):
                table_path = node._v_pathname
                if '/singles' in table_path:
                    if 'singles_old' in table_path:
                        continue
                    type_ = type(node.description.mas_ch1_low)
                    if type_ == tables.UInt16Col:
                        logging.debug(f'Found: {table_path}')
                        singles_tables.append(table_path)
                    elif type_ == tables.Int32Col:
                        logging.debug(f'Skipping migrated: {table_path}')
                        continue
                    else:
                        logging.error(f'{table_path} in unknown format!')

        if singles_tables:
            queue[fn] = singles_tables
            logging.info(f'Found {len(singles_tables)} tables in {fn}')

    n = sum(len(v) for v in queue.itervalues())
    logging.info(f'Found {n} unmigrated tables in {len(queue)} datastore files.')
    return queue


def migrate():
    """
    Find unmigrated tables in datastore
    migrate tables
    check datastore again for unmigrated tables
    """

    logging.info('******************')
    logging.info('Starting migration')
    logging.info('******************')

    queue = get_queue(DATASTORE_PATH)
    print('migrating:')
    for path in pbar(queue.keys()):
        logging.info(f'Migrating: {path}')
        with tables.open_file(path, 'a') as data:
            migration = MigrateSingles(data)
            for table in queue[path]:
                logging.debug(f'Processing table: {table}')
                migration.migrate_table(table)

    queue = get_queue(DATASTORE_PATH)
    if queue:
        logging.error('Found unprocessed tables after migration')
        for path in queue:
            logging.error(f'Unprocessed tables in: {path}')
            for table in queue[path]:
                logging.error(f'{table}')
    else:
        logging.info('********************')
        logging.info('Migration succesful!')
        logging.info('********************')


if __name__ == '__main__':
    fmt = '%(asctime)s - %(levelname)s - %(message)s'
    logging.basicConfig(filename='migration.log', level=logging.INFO, format=fmt)

    logging.info('Datastore path: %s', DATASTORE_PATH)
    migrate()
    logging.info('Done.')
