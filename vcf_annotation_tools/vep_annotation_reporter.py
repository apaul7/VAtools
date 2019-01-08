#!/usr/bin/env python

import sys
import os
import argparse
import re
from cyvcf2 import VCF
import tempfile
import csv
import binascii

def define_parser():
    parser = argparse.ArgumentParser('vep-annotation-reporter')
    parser.add_argument(
        "input_tsv",
        help="The TSV report file to add VEP annotations to. Required columns are CHROM, POS, REF, ALT. Must be tab-delimited."
    )
    parser.add_argument(
        "input_vcf",
        help="The VCF file with VEP annotations to report."
    )
    parser.add_argument(
        "vep_fields",
        help="The VEP fields to report.",
        nargs='+',
    )
    parser.add_argument(
        "-o", "--output-tsv",
        help="Path to write the output report TSV file. If not provided, the output TSV will be written "
            +"next to the input VCF with a .tsv file ending."
    )
    return parser

def parse_csq_header(vcf_file):
    for header in vcf_file.header_iter():
        info = header.info(extra=True)
        if b'ID' in info.keys() and info[b'ID'] == b'CSQ':
            format_pattern = re.compile('Format: (.*)"')
            match = format_pattern.search(info[b'Description'].decode())
            return match.group(1).split('|')

def parse_csq_entries(csq_entries, csq_fields):
    transcripts = {}
    for entry in csq_entries:
        values = entry.split('|')
        transcript = {}
        for key, value in zip(csq_fields, values):
            transcript[key] = value
        if transcript['Allele'] not in transcripts.keys():
            transcripts[transcript['Allele']] = []
        transcripts[transcript['Allele']].append(transcript)
    return transcripts

def resolve_alleles(entry, csq_alleles):
    alleles = {}
    if entry.is_indel:
        for alt in entry.ALT:
            alt = str(alt)
            if alt[0:1] != entry.REF[0:1]:
                csq_allele = alt
            elif alt[1:] == "":
                csq_allele = '-'
            else:
                csq_allele = alt[1:]
            alleles[alt] = csq_allele
    elif entry.is_sv:
        for alt in alts:
            if len(alt) > len(entry.REF) and 'insertion' in csq_alleles:
                alleles[alt] = 'insertion'
            elif len(alt) < len(entry.REF) and 'deletion' in csq_alleles:
                alleles[alt] = 'deletion'
            elif len(csq_alleles) == 1:
                alleles[alt] = list(csq_alleles)[0]
    else:
        for alt in entry.ALT:
            alt = str(alt)
            alleles[alt] = alt
    return alleles

def transcript_for_alt(transcripts, alt):
    for transcript in transcripts[alt]:
        if 'PICK' in transcript and transcript['PICK'] == '1':
            return transcript
    return transcripts[alt][0]

def decode_hex(string):
    hex_string = string.group(0).replace('%', '')
    return binascii.unhexlify(hex_string).decode('utf-8')

def main(args_input = sys.argv[1:]):
    parser = define_parser()
    args = parser.parse_args(args_input)

    vcf_file = VCF(args.input_vcf)

    csq_fields = parse_csq_header(vcf_file)

    vep = {}
    for variant in vcf_file:
        chr = str(variant.CHROM)
        pos = str(variant.POS)
        ref = str(variant.REF)
        alts = variant.ALT

        if chr not in vep:
            vep[chr] = {}

        if pos not in vep[chr]:
            vep[chr][pos] = {}

        if ref not in vep[chr][pos]:
            vep[chr][pos][ref] = {}

        csq = variant.INFO.get('CSQ')
        if csq is not None:
            transcripts = parse_csq_entries(csq.split(','), csq_fields)
        else:
            for alt in alts:
                vep[chr][pos][ref][alt] = None
            continue
        alleles_dict = resolve_alleles(variant, transcripts.keys())
        for alt in alts:
            if alt not in vep[chr][pos][ref]:
                if alleles_dict[alt] in transcripts:
                    vep[chr][pos][ref][alt] = transcript_for_alt(transcripts, alleles_dict[alt])
                else:
                    vep[chr][pos][ref][alt] = None
            else:
                sys.exit("VEP entry for at CHR %s, POS %s, REF %s , ALT % already exists" % (chr, pos, ref, alt) )


    with open(args.input_tsv, 'r') as input_filehandle:
        reader = csv.DictReader(input_filehandle, delimiter = "\t")
        if args.output_tsv:
            output_file = args.output_tsv
        else:
            (head, sep, tail) = args.input_vcf.rpartition('.vcf')
            output_file = "{}.tsv".format(head)
        output_filehandle = open(output_file, 'w')
        writer = csv.DictWriter(output_filehandle, fieldnames = reader.fieldnames + args.vep_fields, delimiter = "\t")
        writer.writeheader()
        for entry in reader:
            row = entry
            for field in args.vep_fields:
                field_annotations = []
                for alt in entry['ALT'].split(','):
                    vep_annotations = vep[entry['CHROM']][entry['POS']][entry['REF']][alt]
                    if vep_annotations is not None and field in vep_annotations:
                        annotation = vep_annotations[field]
                        decoded_annotation = re.sub(r'%[0-9|A-F][0-9|A-F]', decode_hex, annotation)
                        field_annotations.append(decoded_annotation)
                    else:
                        field_annotations.append('-')
                row[field] = ','.join(field_annotations)
            writer.writerow(row)
        output_filehandle.close()

if __name__ == '__main__':
    main()
