#!/usr/bin/env python2

import argparse
import contextlib
import functools
import gzip
import json
import multiprocessing
import os
import sys
import time
from itertools import chain, islice

import parsing
import pymongo
import pysam
import sequences
from flask import Config

argparser = argparse.ArgumentParser(description = 'Tool for creating and populating Bravo database.')
argparser_subparsers = argparser.add_subparsers(help = '', dest = 'command')

argparser_gene_models = argparser_subparsers.add_parser('genes', help = 'Creates and populates MongoDB collections for gene models.')
argparser_gene_models.add_argument('-t', '--canonical-transcripts', metavar = 'file', required = True, type = str, dest = 'canonical_transcripts_file', help = 'File (compressed using Gzip) with a list of canonical transcripts. Must have two columns without a header. First column stores Ensembl gene ID, second column stores Ensembl transcript ID.')
argparser_gene_models.add_argument('-m', '--omim', metavar = 'file', required = True, type = str, dest = 'omim_file', help = 'File (compressed using Gzip) with genes descriptions from OMIM. Required columns separated by tab: Gene stable ID, Transcript stable ID, MIM gene accession, MIM gene description.')
argparser_gene_models.add_argument('-f', '--dbnsfp', metavar = 'file', required = True, type = str, dest = 'genenames_file', help = 'File (compressed using Gzip) with gene names from HGNC. Required columns separated by tab: symbol, name, alias_symbol, prev_name, ensembl_gene_id.')
argparser_gene_models.add_argument('-g', '--gencode', metavar = 'file', required = True, type = str, dest = 'gencode_file', help = 'File from GENCODE in compressed GTF format.')

argparser_users = argparser_subparsers.add_parser('users', help = 'Creates MongoDB collection for user data.')

argparser_whitelist = argparser_subparsers.add_parser('whitelist', help = 'Creates and populates MongoDB collection for whitelist\'ed users.')
argparser_whitelist.add_argument('-w', '--whitelist', metavar = 'file', required = True, type = str, dest = 'whitelist_file', help = 'Emails whitelist file. One email per line.')

argparser_dbsnp = argparser_subparsers.add_parser('dbsnp', help = 'Creates and populates MongoDB collection with dbSNP variants.')
argparser_dbsnp.add_argument('-d', '--dbsnp', metavar = 'file', required = True, type = str, nargs = '+', dest = 'dbsnp_files', help = 'File (or multiple files split by chromosome) with variants from dbSNP, compressed using bgzip and indexed using tabix. File must have three tab-delimited columns without header: integer part of rsId, chromosome, position (0-based).')
argparser_dbsnp.add_argument('-t', '--threads', metavar = 'number', required = False, type = int, default = 1, dest = 'threads', help = 'Number of threads to use.')

argparser_metrics = argparser_subparsers.add_parser('metrics', help = 'Creates and populates MongoDB collection with pre-calculated metrics across all variants.')
argparser_metrics.add_argument('-m', '--metrics', metavar = 'file', required = True, type = str, dest = 'metrics_file', help = 'File with the pre-calculated metrics across all variants. Every metric must be stored on a separate line in JSON format.')

argparser_variants = argparser_subparsers.add_parser('variants', help = 'Creates and populates MongoDB collection for variants.')
argparser_variants.add_argument('-v', '--variants', metavar = 'file', required = True, type = str, nargs = '+', dest = 'variants_files', help = 'VCF/BCF file (or multiple files split by chromosome) with variants, compressed using bgzip and indexed using tabix.')
argparser_variants.add_argument('-t', '--threads', metavar = 'number', required = True, type = int, default = 1, dest = 'threads', help = 'Number of thrads to use.')

argparser_bamcache = argparser_subparsers.add_parser('bam_cache', help = 'Creates MongoDB collection for storing paths to cached BAM\CRAM files for the IGV browser.')

argparser_custom_variants = argparser_subparsers.add_parser('custom_variants', help = 'Creates and populates an additional MongoDB collection for variants. Useful when there is a need to serve multiple different variants sets (e.g. after subsetting samples) through the API.')
argparser_custom_variants.add_argument('-v', '--variants', metavar = 'file', required = True, type = str, nargs = '+', dest = 'variants_files', help = 'VCF/BCF file (or multiple files split by chromosome) with variants, compressed using bgzip and indexed using tabix.')
argparser_custom_variants.add_argument('-n', '--name', metavar = 'name', required = True, type = str, dest = 'collection_name', help = 'MongoDB destination collection name.')
argparser_custom_variants.add_argument('-t', '--threads', metavar = 'number', required = True, type = int, default = 1, dest = 'threads', help = 'Number of thrads to use.')


argparser_percentiles = argparser_subparsers.add_parser('percentiles', help = 'Loads percentiles for each variant from INFO field in the provided VCF. Percentiles in the INFO field must have \'_P\' suffix and store two comma separated values: lower bound and upper bound.')
argparser_percentiles.add_argument('-v', '--variants', metavar = 'file', required = True, type = str, nargs = '+', dest = 'variants_files', help = 'VCF/BCF file (or multiple files split by chromosome) with variants, compressed using bgzip and indexed using tabix.')
argparser_percentiles.add_argument('-t', '--threads', metavar = 'number', required = True, type = int, default = 1, dest = 'threads', help = 'Number of thrads to use.')


#argparser_update_variants = argparser_subparsers.add_parser('update', help = 'Updates variants collection with provided INFO fields from input VCF/BCF.')
#argparser_update_variants.add_argument('-v', '--variants', metavar = 'file', required = True, type = str, nargs = '+', dest = 'variants_files', help = 'VCF/BCF file (or multiple files split by chromosome) with variants, compressed using bgzip and indexed using tabix.')
#argparser_update_variants.add_argument('-t', '--threads', metavar = 'number', required = True, type = int, default = 1, dest = 'threads', help = 'Number of threads to use.')


def get_db_connection():
    mongo = pymongo.MongoClient(host = mongo_host, port = mongo_port, connect = False)
    return mongo[mongo_db_name]


def load_gene_models(canonical_transcripts_file, omim_file, genenames_file, gencode_file):
    """Creates and populates the following MongoDB collections: genes, transcripts, exons.

    Arguments:
    canonical_transcripts_file -- file with a list of canonical transcripts. No header. Two columns: Ensebl gene ID, Ensembl transcript ID.
    omim_file -- file with genes descriptions from OMIM. Required columns separated by tab: Gene stable ID, Transcript stable ID, MIM gene accession, MIM gene description.
    genenames_file -- file with gene names from HGNC. Required columns separated by tab: symbol, name, alias_symbol, prev_name, ensembl_gene_id.
    gencode_file -- file from GENCODE in compressed GTF format.
    """
    db = get_db_connection()
    db.genes.drop()
    db.transcripts.drop()
    db.exons.drop()

    canonical_transcripts = dict()
    with gzip.GzipFile(canonical_transcripts_file, 'r') as ifile:
        for gene, transcript in parsing.get_canonical_transcripts(ifile):
            canonical_transcripts[gene] = transcript

    omim_annotations = dict()
    with gzip.GzipFile(omim_file, 'r') as ifile:
        for gene, transcript, accession, description in parsing.get_omim_associations(ifile):
            omim_annotations[gene] = (accession, description) # TODO: what about transcript?

    genenames = dict()
    with gzip.GzipFile(genenames_file, 'r') as ifile:
        for gene in parsing.get_genenames(ifile):
            genenames[gene['ensembl_gene']] = (gene['gene_full_name'], gene['gene_other_names'])

    with gzip.GzipFile(gencode_file, 'r') as ifile:
        for gene in parsing.get_regions_from_gencode_gtf(ifile, {'gene'}):
            gene_id = gene['gene_id']
            if gene_id in canonical_transcripts:
                gene['canonical_transcript'] = canonical_transcripts[gene_id]
            if gene_id in omim_annotations:
                gene['omim_accession'] = omim_annotations[gene_id][0]
                gene['omim_description'] = omim_annotations[gene_id][1]
            if gene_id in genenames:
                gene['full_gene_name'] = genenames[gene_id][0]
                gene['other_names'] = genenames[gene_id][1]
            db.genes.insert_one(gene)
    db.genes.create_indexes([pymongo.operations.IndexModel(key) for key in ['gene_id', 'gene_name', 'other_names', 'xstart', 'xstop']])
    sys.stdout.write('Inserted {} gene(s).\n'.format(db.genes.count()))

    with gzip.GzipFile(gencode_file, 'r') as ifile:
        db.transcripts.insert_many(transcript for transcript in parsing.get_regions_from_gencode_gtf(ifile, {'transcript'}))
    db.transcripts.create_indexes([pymongo.operations.IndexModel(key) for key in ['transcript_id', 'gene_id']])
    sys.stdout.write('Inserted {} transcript(s).\n'.format(db.transcripts.count()))

    with gzip.GzipFile(gencode_file, 'r') as ifile:
        db.exons.insert_many(exon for exon in parsing.get_regions_from_gencode_gtf(ifile, {'exon', 'CDS', 'UTR'}))
    db.exons.create_indexes([pymongo.operations.IndexModel(key) for key in ['exon_id', 'transcript_id', 'gene_id']])
    sys.stdout.write('Inserted {} exon(s).\n'.format(db.exons.count()))


def create_users():
    """Creates users collection in MongoDB.

    """
    db = get_db_connection()
    db.users.drop()
    db.users.create_index('user_id')


def load_whitelist(whitelist_file):
    """Creates and populates MongoDB collections for whitelist'ed users.

    Arguments:
    whitelist_file -- file with emails of whitelist'ed users. One email per line.
    """
    db = get_db_connection()
    db.whitelist.drop()
    with open(whitelist_file, 'r') as ifile:
        for line in ifile:
            email = line.strip()
            if email:
                db.whitelist.insert({'user_id': email})
    db.whitelist.create_index('user_id')
    sys.stdout.write('Inserted {} email(s).\n'.format(db.whitelist.count()))


def get_file_contig_pairs(files):
    """Creates [(file, chrom), (file, chrom), ...] list.

    Arguments:
    filenames -- list of one or more tabix'ed files.
    """
    file_contig_pairs = []
    for file in files:
        with pysam.Tabixfile(file) as tabix:
            for contig in tabix.contigs:
                file_contig_pairs.append((file, contig))
    return sorted(file_contig_pairs, key = lambda x: x[1]) # stable sort to make same chromsome entries adjacent


def _write_to_collection(args, collection, reader, histograms = True):
    file, chrom = args
    if chrom != 'PAR':
        db = get_db_connection()
        documents = reader(file, chrom, None, None, histograms)
        for document in documents:
            db[collection].insert_many(chain([document], islice(documents, 99999))) # insert in chunks of 100000 documents


def load_dbsnp(dbsnp_files, threads):
    """Creates and populates MongoDB collection for dbSNP variants.

    Arguments:
    dbsnp_files -- list of one or more files with variants compressed using bgzip and indexed using tabix. File(s) must have 3 tab-delimited columns without header: integer part of rsId, chromosome, position (0-based).
    threads -- number of threads to use.
    """
    db = get_db_connection()
    db.dbsnp.drop()
    with contextlib.closing(multiprocessing.Pool(threads)) as threads_pool:
        threads_pool.map(functools.partial(_write_to_collection, collection = 'dbsnp', reader = parsing.get_snp_from_dbsnp_file), get_file_contig_pairs(dbsnp_files))
    db.dbsnp.create_indexes([pymongo.operations.IndexModel(key) for key in ['xpos', 'rsid']])
    sys.stdout.write('Inserted {} variant(s).\n'.format(db.dbsnp.count()))


def load_metrics(metrics_file):
    """Creates and populates MongoDB collection for metrics calculated across all variants.

    Arguments:
    metrics_file -- file with metrics. One metric per line in JSON format.
    """
    db = get_db_connection()
    db.metrics.drop()
    with open(metrics_file, 'r') as ifile:
        for line in ifile:
            metric = json.loads(line)
            db.metrics.insert(metric)
    db.metrics.create_index('metric')
    sys.stdout.write('Inserted {} metric(s).\n'.format(db.metrics.count()))


def load_variants(variants_files, threads):
    """Creates and populates MongoDB collection for variants.

    Arguments:
    variants_files -- list of one or more VCF/BCF files with variants (no genotypes) compressed using bgzip and indexed using tabix.
    threads -- number of threads to use.
    """
    db = get_db_connection()
    db.variants.drop()
    with contextlib.closing(multiprocessing.Pool(threads)) as threads_pool:
        threads_pool.map(functools.partial(_write_to_collection, collection = 'variants', reader = parsing.get_variants_from_sites_vcf), get_file_contig_pairs(variants_files))
    db.variants.create_indexes([pymongo.operations.IndexModel(key) for key in ['xpos', 'xstop', 'rsids', 'filter']])
    sys.stdout.write('Inserted {} variant(s).\n'.format(db.variants.count()))


def create_sequence_cache(collection_name):
    """Creates Mongo collection with unique index to store paths to cached BAM\CRAM files for the IGV browser.\
     Important: Mongo will not do any cleaning if cache becomes too large."

    Arguments:
    collection_name -- name of MongoDB collection that will store paths to cached files.
    """
    db = get_db_connection()
    sequences.SequencesClient.create_cache_collection_and_index(db, collection_name)


def load_custom_variants(variants_files, collection_name, threads):
    """Creates and populates MongoDB collection with given name for additional variants.

    Arguments:
    variants_files -- list of one or more VCF/BCF files with variants (no genotypes) compressed using bgzip and indexed using tabix.
    collection_name -- name of MongoDB collection that will store variants.
    threads -- number of threads to use.
    """
    db = get_db_connection()
    if collection_name in db.collection_names():
        db[collection_name].drop()
    with contextlib.closing(multiprocessing.Pool(threads)) as threads_pool:
        threads_pool.map(functools.partial(_write_to_collection, collection = collection_name, reader = parsing.get_variants_from_sites_vcf, histograms = False), get_file_contig_pairs(variants_files))
    db[collection_name].create_indexes([pymongo.operations.IndexModel(key) for key in ['xpos', 'xstop', 'filter']])
    sys.stdout.write('Inserted {} variant(s).\n'.format(db[collection_name].count()))


def _load_percentiles_from_vcf(vcf):
    db = get_db_connection()
    n_variants = 0
    n_matched = 0
    n_modified = 0
    with gzip.GzipFile(vcf, 'r') as ivcf:
        start_time = time.time()
        requests = []
        for variant in parsing.get_variants_from_sites_vcf_only_percentiles(ivcf):
            requests.append(pymongo.operations.UpdateOne(
                {'xpos': variant['xpos'], 'ref': variant['ref'], 'alt': variant['alt']},
                {'$set': {'quality_metrics_percentiles': variant['percentiles']}},
                upsert = False))
            n_variants += 1
            if n_variants % 1000000 == 0:
                res = db.variants.bulk_write(requests, ordered = False)
                n_matched += res.matched_count
                n_modified += res.modified_count
                requests = []
                print('VCF {}. Processed {} variant(s) in {} second(s), {} matched, {} modified.'.format(vcf, n_variants, int(time.time() - start_time), n_matched, n_modified)) 
        if len(requests) > 0:
            res = db.variants.bulk_write(requests, ordered = False)
            n_matched += res.matched_count
            n_modified += res.modified_count
            print('Finished. VCF {}. Processed {} variant(s) in {} second(s), {} matched, {} modified.'.format(vcf, n_variants, int(time.time() - start_time), n_matched, n_modified))


def load_percentiles(variant_files, threads):
    """Loads percentiles.

    Arguments:
    variants_files -- list of one or more VCF/BCF files with variants (no genotypes) compressed using bgzip and indexed using tabix.
    threads -- number of threads to use.
    """
    with contextlib.closing(multiprocessing.Pool(threads)) as threads_pool:
        threads_pool.map_async(_load_percentiles_from_vcf, variant_files).get(9999999)


def _update_collection(args, collection, reader):
    file, chrom = args
    db = get_db_connection()
    n_documents = 0
    n_matched = 0
    n_modified = 0
    start_time = time.time()
    requests = []
    for document in reader(file, chrom, None, None):
        requests.append(pymongo.operations.UpdateOne(
            {'xpos': document['xpos'], 'ref': document['ref'], 'alt': document['alt']},
            {'$set': {k: v for k, v in document.items() if k not in { 'xpos', 'ref', 'alt' }}},
            upsert = False))
        n_documents += 1
        if n_documents % 100000 == 0:
            res = db[collection].bulk_write(requests, ordered = False)
            n_matched += res.matched_count
            n_modified += res.modified_count
            requests = []
            sys.stdout.write('VCF/BCF {}. Processed {} document(s) in {} second(s), {} matched, {} modified.\n'.format(file, n_documents, int(time.time() - start_time), n_matched, n_modified))
    if len(requests) > 0:
        res = db[collection].bulk_write(requests, ordered = False)
        n_matched += res.matched_count
        n_modified += res.modified_count
        sys.stdout.write('Finished. VCF/BCF {}. Processed {} document(s) in {} second(s), {} matched, {} modified.\n'.format(file, n_documents, int(time.time() - start_time), n_matched, n_modified))

'''
def update_variants(variants_files, threads):
    """Updates varians collection with custom fields.

    Arguments:
    variants_files -- list of one or more VCF/BCF files with variants (no genotypes) compressed using bgzip and indexed using tabix.
    threads -- number of threads to use.
    """
    with contextlib.closing(multiprocessing.Pool(threads)) as threads_pool:
        threads_pool.map(functools.partial(_update_collection, collection = 'variants', reader = ), get_file_contig_pairs(variants_files))
'''

if __name__ == '__main__':
    global mongo_host
    global mongo_port
    global mongo_db_name

    args = argparser.parse_args()

    config = Config(os.path.dirname(os.path.realpath(__file__)))
    # Load default config
    config.from_object('config.default')
    # Load instance configuration if exists
    config.from_pyfile('config.py', silent = True)
    # Load configuration file specified in BRAVO_CONFIG_FILE environment variable if exists
    config.from_envvar('BRAVO_CONFIG_FILE', silent = True)

    mongo_host = config['MONGO']['host']
    mongo_port = config['MONGO']['port']
    mongo_db_name = config['MONGO']['name']
    igv_cache_collection_name = config['IGV_CACHE_COLLECTION']

    if args.command == 'genes':
        sys.stdout.write('Start loading genes to {} database.\n'.format(mongo_db_name))
        load_gene_models(args.canonical_transcripts_file, args.omim_file, args.genenames_file, args.gencode_file)
        sys.stdout.write('Done loading genes to {} database.\n'.format(mongo_db_name))
    elif args.command == 'users':
        sys.stdout.write('Creating users collection in {} database.\n'.format(mongo_db_name))
        create_users()
        sys.stdout.write('Done creating users collection in {} database.\n'.format(mongo_db_name))
    elif args.command == 'whitelist':
        sys.stdout.write('Creating whitelist collection in {} database.\n'.format(mongo_db_name))
        load_whitelist(args.whitelist_file)
        sys.stdout.write('Done creating whitelist collection in {} database.\n'.format(mongo_db_name))
    elif args.command == 'dbsnp':
        sys.stdout.write('Creating dbSNP collection in {} database.\n'.format(mongo_db_name))
        sys.stdout.write('Using {} thread(s).\n'.format(args.threads))
        load_dbsnp(args.dbsnp_files, args.threads)
        sys.stdout.write('Done creating dbSNP collection in {} database.\n'.format(mongo_db_name))
    elif args.command == 'metrics':
        sys.stdout.write('Creating metrics collection in {} database.\n'.format(mongo_db_name))
        load_metrics(args.metrics_file)
        sys.stdout.write('Done creating metrics collection in {} databases.\n'.format(mongo_db_name))
    elif args.command == 'variants':
        sys.stdout.write('Creating variants collection in {} database.\n'.format(mongo_db_name))
        load_variants(args.variants_files, args.threads)
        sys.stdout.write('Done creating variants collection in {} database.\n'.format(mongo_db_name))
    elif args.command == 'bam_cache':
        sys.stdout.write('Creating {} collection in {} database.\n'.format(igv_cache_collection_name, mongo_db_name))
        create_sequence_cache(igv_cache_collection_name)
        sys.stdout.write('Done creating {} collection in {} database.\n'.format(igv_cache_collection_name, mongo_db_name))
    elif args.command == 'custom_variants':
        sys.stdout.write('Creating {} collection in {} database.\n'.format(args.collection_name, mongo_db_name))
        load_custom_variants(args.variants_files, args.collection_name, args.threads)
        sys.stdout.write('Done creating {} collection in {} database.\n'.format(args.collection_name, mongo_db_name))
    elif args.command == 'percentiles':
        sys.stdout.write('Loading percentiles into {} database.\n'.format(mongo_db_name))
        load_percentiles(args.variants_files, args.threads)
        sys.stdout.write('Done loading percentiles into {} database.\n'.format(mongo_db_name))
#    elif args.command == 'update':
#        sys.stdout.write('Updating variants collection in {} database.\n'.format(mongo_db_name))
#        update_variants(args.variants_files, args.threads)
#        sys.stdout.write('Done updating variants collection in {} databased.\n'.format(mongo_db_name))
    else:
        raise Exception('Command {} is not supported.'.format(args.command))
