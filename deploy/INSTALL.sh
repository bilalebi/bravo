#!/bin/bash

set -e

RED="\033[0;31m"
GREEN="\033[32m"
NOCOLOR="\033[0m"

setup_ensembl_api() {
    echo -e "${GREEN}=> Setup BioPerl and Ensembl API${NOCOLOR}"
    mkdir src
    cd src
    wget ftp://ftp.ensembl.org/pub/ensembl-api.tar.gz
    wget https://cpan.metacpan.org/authors/id/C/CJ/CJFIELDS/BioPerl-1.6.1.tar.gz
    tar -zxf ensembl-api.tar.gz
    tar -zxf BioPerl-1.6.1.tar.gz
    cd ..
    PERL5LIB=${PERL5LIB}:${PWD}/src/BioPerl-1.6.1
    PERL5LIB=${PERL5LIB}:${PWD}/src/ensembl/modules
    PERL5LIB=${PERL5LIB}:${PWD}/src/ensembl-compara/modules
    PERL5LIB=${PERL5LIB}:${PWD}/src/ensembl-variation/modules
    PERL5LIB=${PERL5LIB}:${PWD}/src/ensembl-funcgen/modules
    export PERL5LIB
}

download_canonical_transcripts() {
    # we should not worry about human genome build version here, because we don't need genomic coordinates
    # we want just a specific version of Ensembl
    dbversion="homo_sapiens_core_91_38"
    echo -e "${GREEN}=> Downloading canonical transcripts from Ensembl 91${NOCOLOR}"
    perl download_canonical_transcripts.pl homo_sapiens_core_91_38 | gzip -c > canonical_transcripts.txt.gz
}

download_OMIM() {
    dbversion=`curl "http://useast.ensembl.org/biomart/martservice?type=registry" | grep ENSEMBL_MART_ENSEMBL | grep -oP 'displayName="\K[^"]*'`
    echo -e "${GREEN}=> Downloading OMIM descriptions from BioMart ${dbversion}${NOCOLOR}"
    wget -O - 'http://www.ensembl.org/biomart/martservice?query=<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE Query><Query virtualSchemaName="default" formatter="TSV" header="1" uniqueRows="0" count="" datasetConfigVersion="0.6"><Dataset name="hsapiens_gene_ensembl" interface="default"><Attribute name="ensembl_gene_id"/><Attribute name="ensembl_transcript_id"/><Attribute name="mim_gene_accession"/><Attribute name="mim_gene_description"/></Dataset></Query>' | gzip -c > omim.txt.gz
}

download_GENCODE() {
    genome_build=$1
    if [ "$genome_build" == "hg38" ]; then
        echo -e "${GREEN}=> Downloading GENCODE 27 for human genome version ${genome_build}${NOCOLOR}"
        wget -O gencode.gtf.gz ftp://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_27/gencode.v27.annotation.gtf.gz
    elif [ "$genome_build" == "hg19" ]; then
        echo -e "${GREEN}=> Downloading GENCODE 27 for human genome version ${genome_build}${NOCOLOR}"
        wget -O gencode.gtf.gz ftp://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_27/GRCh37_mapping/gencode.v27lift37.annotation.gtf.gz
    else
        echo "Human genome build ${genome_build} is not supported!"
        exit 1
    fi
}

download_genenames() {
    echo -e "${GREEN}=> Downloading gene names from HGNC${NOCOLOR}"
    wget -O hgnc.txt ftp://ftp.ebi.ac.uk/pub/databases/genenames/new/tsv/hgnc_complete_set.txt
    gzip hgnc.txt   
}

download_dbSNP() {
    genome_build=$1
    if [ "$genome_build" == "hg38" ]; then
        echo -e "${GREEN}=> Downloading dbSNP 150 for human genome version ${genome_build}${NOCOLOR}"
        wget -O test.bcp.gz ftp://ftp.ncbi.nlm.nih.gov/snp//organisms/human_9606_b150_GRCh38p7/database/data/organism_data/b150_SNPChrPosOnRef_108.bcp.gz
    elif [ "$genome_build" == "hg19" ]; then 
        echo -e "${GREEN}=> Downloading dbSNP 150 for human genome version ${genome_build}${NOCOLOR}"
        wget -O test.bcp.gz ftp://ftp.ncbi.nlm.nih.gov/snp//organisms/human_9606_b150_GRCh37p13/database/data/organism_data/b150_SNPChrPosOnRef_105.bcp.gz
    else
        echo "Human genome build ${genome_build} is not supported!"
        exit 1
    fi
}


echo -e "${RED}DOWNLOADING EXTERNAL DATA${NOCOLOR}"
setup_ensembl_api
download_canonical_transcripts
download_OMIM
download_GENCODE hg38
download_genenames

#download_dbSNP hg38