#!/usr/bin/env python

'''
Build a graph genome from a linear reference genome and set of variants
'''

import sys
import argparse

import iohelp
import variant
from util import *

VERSION = '0.0.1'

class Builder:
    def __init__(self, genome, vars, r):
        self.genome = genome
        self.vars = vars
        self.num_v = len(vars)
        self.r = r

    def write_hisat(self, variants, filename):
        '''
        Write variants in HISAT2 format for graph genome
        variants: path to 1ksnp file
        filename: hisat2 snp file to write to
        '''
        iohelp.write_vars(variants, [v.pos+1 for v in self.vars], filename)

    def write_erg(self, filename):
        '''
        Write graph genome in flattened ERG format from Satya et al.
        '''
        print('Writing ERG')
        print(self.num_v)
        print(self.r)
        with open(filename, 'w') as f:
            pc_counts = dict()
            for chrom,seq in self.genome.items():
                pc_counts[chrom] = [0] * len(seq)
            for i in range(self.num_v):
                chrom = self.vars[i].chrom
                pos = self.vars[i].pos

                # Number of variants in window starting at this one
                k = 1
                while i+k < self.num_v and self.vars[i+k].chrom == chrom and self.vars[i+k].pos < pos+self.r:
                    k += 1

                iter = PseudocontigIterator(self.genome[chrom], self.vars[i:i+k], self.r)
                pc = iter.next()
                while pc:
                    pc_counts[chrom][iter.start] += 1
                    f.write('>' + chrom + ':' + str(iter.start) + ':' + str(pc_counts[chrom][iter.start]) + ':\n')
                    for n in range(0, len(pc), 60):
                        f.write(pc[n:n+60] + '\n')

                    pc = iter.next()
        print('Done')

def top_vars(variants, ordered, pct):
    '''
    Return the set of top variants, according to some ordering
    
    variants: List of variants
    ordered: File containing sorted variants, labeled by position
    pct: Percentage of variants to return
    '''
    with open(ordered, 'r') as f:
        ordered_vars = [(v.split(',')[0],int(v.split(',')[1])) for v in f.readline().split('\t')]
    num_targets = int(len(ordered_vars) * pct / 100.0)
    targets = ordered_vars[:num_targets]
    targets.sort()

    selected = []
    curr_id = 0
    for v in variants:
        if v.chrom == targets[curr_id][0] and v.pos == targets[curr_id][1]-1:
            selected.append(v)
            curr_id += 1
            if curr_id == num_targets:
                break

    print('Found %d / %d variants' % (len(selected), len(targets)))
    return selected

def go(args):
    if args.window_size:
        r = args.window_size
    else:
        r = 35

    genome = iohelp.read_genome(args.reference, None)
    variants = iohelp.parse_1ksnp(args.vars)

    if args.sorted:
        targets = top_vars(variants, args.sorted, args.pct)
        builder = Builder(genome, targets, r)
    else:
        builder = Builder(genome, variants, r)

    if args.hisat:
        builder.write_hisat(args.vars, args.hisat)
    if args.erg:
        builder.write_erg(args.erg)

if __name__ == '__main__':
    if '--version' in sys.argv:
        print('FORGe v' + VERSION)
        sys.exit(0)

    # Print file's docstring if -h is invoked
    parser = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument('--reference', type=str, required=True, 
        help='Path to fasta file containing reference genome')
    parser.add_argument("--vars", type=str, required=True,
        help="Path to 1ksnp file containing variant information")
    parser.add_argument('--window-size', type=int,
        help="Radius of window (i.e. max read length) to use. Larger values will take longer. Default: 35")
    parser.add_argument('--hisat', type=str, required=False, help='Path to file to write HISAT2 --snp information')
    parser.add_argument('--erg', type=str, required=False, help='Path to fasta file to write additional pseudocontigs for ERG alignment')
    parser.add_argument('--sorted', type=str, required=False, help='Path to file containing variant ranking information')
    parser.add_argument('--pct', type=int, required=False, help='Percentage of variants to include in graph genome')

    args = parser.parse_args(sys.argv[1:])
    go(args)

