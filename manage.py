#!/usr/bin/env python2

import sys
from flask_script import Manager
import exac


manager = Manager(exac.app)


@manager.command
def load_variants_file():
    exac.load_variants_file()


@manager.command
def load_gene_models():
    exac.load_gene_models()


@manager.command
def load_dbsnp_file():
    exac.load_dbsnp_file()


@manager.command
def precalculate_metrics():
    exac.precalculate_metrics()


@manager.command
def create_users():
    exac.create_users()


@manager.command
def all_variants():
    exac.load_variants_file()
    exac.precalculate_metrics()


@manager.option('-c', '--collection', dest = 'collection', type = str, required = True, help = 'Destination Mongo collection name.') 
@manager.option('-v', '--vcf', dest = 'vcfs', type = str, nargs = '+', required = True, help = 'Input VCF name.')
def load_custom_variants_file(collection, vcfs):
    "Loads variants from the specified VCF file(s) into a new Mongo collection.\
     Useful when there is a need to serve multiple different variants sets (e.g. after subsetting samples) through the API."

    if not collection.strip():
        sys.exit("Collection name must be a non-empty string.")
    if not all(x.strip() for x in vcfs):
        sys.exit("VCF file name(s) must be a non-empty string(s).")
    exac.load_custom_variants_file(collection, vcfs)


@manager.option('-c', '--collection', dest = 'collection', type = str, required = False, help = 'Mongo collection name to store paths to cached BAM/CRAM files.')
def create_sequence_cache(collection):
    "Creates Mongo collection with unique index to store paths to cached BAM\CRAM files for the IGV browser.\
     Important: Mongo will not do any cleaning if cache becomes too large."
    
    if collection is not None and not collection.strip():
        sys.exit("Collection name must be a non-empty string.")
    exac.create_sequence_cache(collection)

if __name__ == "__main__":
    manager.run()

