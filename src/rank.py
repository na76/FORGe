#! /usr/bin/env python2.7

'''
Rank a set of variants for inclusion in a graph genome, from highest to lowest priority
'''

import sys
import argparse
import jellyfish
import io
import variant
from util import *
import time

VERSION = '0.0.1'

class VarRanker:
    def __init__(self, genome, variants, r, phasing, max_v):
        self.genome = genome
        self.chrom_lens = dict()
        for chrom, seq in genome.items():
            self.chrom_lens[chrom] = len(seq)

        self.variants = variants
        self.num_v = len(variants)
        self.r = r

        if phasing:
            self.hap_parser = io.HaplotypeParser(phasing)

        self.max_v_in_window = max_v

        self.h_ref = None
        self.h_added = None

        self.wgt_ref = None
        self.wgt_added = None

        self.curr_vars = None

    def avg_read_prob(self):
        #self.wgt_ref = 0.778096
        #self.wgt_added = 0.002113

        if self.wgt_ref and self.wgt_added:
            return

        variants = self.variants

        # Average probability (weighted by genome length) of a specific read from the linear genome being chosen 
        total_prob_ref = 0
        count_ref = 0

        # Average probability (weighted by genome length) of a specific read from the added pseudocontigs being chosen 
        total_prob_added = 0
        count_added = 0

        if self.hap_parser:
            self.hap_parser.reset_chunk()

        num_v = len(variants)
        r = self.r

        var_i = 0
        amb = 0.0
        last_i, last_j, last_pref, last_added = -1, -1, -1, -1
        for chrom, seq in self.genome.items():
            print('Processing chrom %s' % chrom)
            num_reads = self.chrom_lens[chrom] - r + 1
            count_ref += num_reads
            for i in range(num_reads):
                read = seq[i:i+r]
                if 'N' in read or 'M' in read or 'R' in read:
                    continue

                #total_prob_ref += 1

                # Set [var_i, var_j) to the range of variants contained in the current read
                while var_i < num_v and variants[var_i].chrom == chrom and variants[var_i].pos < i:
                    var_i += 1
                var_j = var_i
                while var_j < num_v and variants[var_i].chrom == chrom and variants[var_j].pos < i+r:
                    var_j += 1
                num_vars = var_j - var_i

                if num_vars == 0:
                    total_prob_ref += 1
                    continue

                '''
                counts = [variants[n].num_alts for n in range(var_i, var_j)]
                p = 1 - self.prob_read(variants, range(var_i, var_j), [0]*num_vars)
                total_prob_ref -= p
                total_prob_added += p
                num_pcs = 1
                for c in range(var_i, var_j):
                    num_pcs *= (variants[c].num_alts + 1)
                count_added += num_pcs-1
                
                curr_count_added = 0
                counts = [variants[n].num_alts for n in range(var_i, var_j)]
                total_prob_ref2 += self.prob_read(variants, range(var_i, var_j), [0]*num_vars)

                curr_p = self.prob_read(variants, range(var_i, var_j), [0]*num_vars)

                vec = get_next_vector(num_vars, counts, [0]*num_vars)
                while vec:
                    p = self.prob_read(variants, range(var_i, var_j), vec)
                    curr_p += p
                    total_prob_ref -= p
                    total_prob_added += p
                    count_added += 1
                    curr_count_added += 1

                    vec = get_next_vector(num_vars, counts, vec)

                if abs(1 - curr_p) > 0.001:
                    print('%d (%d - %d)' % (num_vars, var_i, var_j))
                    print('Total prob: %f' % curr_p)
                '''

                if var_i == last_i and var_j == last_j:
                    p_ref = last_pref
                    p_alts = 1 - p_ref
                    count_added += last_added-1
                else:
                    last_added = 1
                    for c in range(var_i, min(var_j, var_i+self.max_v_in_window)):
                        last_added *= (variants[c].num_alts + 1)
                    count_added += last_added-1

                    p_ref = self.prob_read_ref(variants, range(var_i, var_j))
                    p_alts = 1 - p_ref
                total_prob_ref += p_ref
                total_prob_added += p_alts

                last_i = var_i
                last_j = var_j
                last_pref = p_ref

        self.wgt_ref = float(total_prob_ref) / count_ref
        self.wgt_added = float(total_prob_added) / count_added
        print('Avg probability of reads in ref:  %f' % self.wgt_ref)
        print('Avg probability of added reads:   %f' % self.wgt_added)

    def count_kmers_ref(self):
        if self.h_ref:
            return

        # Create new Jellyfish counter and count all kmers in reference genome
        jellyfish.MerDNA.k(self.r)
        self.h_ref = jellyfish.HashCounter(1024, 5)

        for chrom in self.genome.values():
            mers = jellyfish.string_canonicals(chrom)
            for m in mers:
                self.h_ref.add(m, 1)

    def count_kmers_added(self):
        if self.h_added:
            return

        total = 0
        total_r = 0

        jellyfish.MerDNA.k(self.r)
        self.h_added = jellyfish.HashCounter(1024, 5)

        for i in range(self.num_v):
            chrom = self.variants[i].chrom
            pos = self.variants[i].pos

            # Number of variants in window starting at this one
            k = 1
            while i+k < self.num_v and self.variants[i+k].chrom == chrom and self.variants[i+k].pos < pos+self.r:
                k += 1

            if k > self.max_v_in_window:
                alt_freqs = [(sum(self.variants[i+j].probs), i+j) for j in range(1, k)]
                ids = [f[1] for f in sorted(alt_freqs, reverse=True)[:self.max_v_in_window-1]]
                it = PseudocontigIterator(self.genome[chrom], [self.variants[i]]+[self.variants[v] for v in ids], self.r)
            else:
                it = PseudocontigIterator(self.genome[chrom], self.variants[i:i+k], self.r)

            pseudocontig = it.next()
            while pseudocontig:
                # Add to jellyfish
                mers = jellyfish.string_canonicals(pseudocontig)
                for m in mers:
                    self.h_added.add(m, 1)

                #total += 1
                #total_r += len(pseudocontig) - self.r + 1

                pseudocontig = it.next()

        #print('%d total pseudocontigs' % total)
        #print('%d total reads' % total_r)

    def prob_read(self, variants, var_ids, vec):
        '''
            Probability that a read contains the allele vector vec
            Simultaneously computes probabilities for all haplotypes of the given variants to save time
        '''

        if not self.curr_vars or not (self.curr_vars == var_ids):
            self.curr_vars = var_ids
            counts = [variants[v].num_alts for v in var_ids]
            num_v = len(var_ids)
            self.counts = counts
            if self.hap_parser:
                # Initialize freqs based on population haplotype data
                self.freqs = self.hap_parser.get_freqs(var_ids, counts)
            else:
                # Inititalize freqs based on independently-assumed allele frequencies
                num_vecs = 1
                for c in counts:
                    num_vecs *= (c+1)
                freqs = [0] * num_vecs
                vec = [0] * num_v
                while vec:
                    p = 1
                    for i in range(num_v):
                        if vec[i]:
                            p *= variants[var_ids[i]].probs[vec[i]-1]
                        else:
                            p *= (1 - sum(variants[var_ids[i]].probs))
                    self.freqs[vec_to_id(vec, counts)] = p
                    v = get_next_vector(num_v, counts, v)

        f = self.freqs[vec_to_id(vec, self.counts)]
        return f

    def prob_read_ref(self, variants, var_ids):
        '''
            Probability that a read is from the reference genome, plus-one smoothed
            Faster than prob_read() when other haplotype probs are unneeded
        '''

        if self.hap_parser:
            self.curr_vars = var_ids
            self.counts = [variants[v].num_alts for v in var_ids]
            return self.hap_parser.get_ref_freq(var_ids, self.counts)
        else:
            p = 1
            for i in range(len(var_ids)):
                p *= (1 - sum(variants[var_ids[i]].probs))
            return p

    def rank(self, method, out_file):
        ordered = None
        ordered_blowup = None
        print(method)
        if method == 'popcov':
            ordered = self.rank_pop_cov()
        elif method == 'popcov-blowup':
            ordered = self.rank_pop_cov(True)
        elif method == 'amb':
            ordered, ordered_blowup = self.rank_ambiguity()

        if ordered:
            with open(out_file, 'w') as f:
                f.write('\t'.join([self.variants[i].chrom + ',' + str(self.variants[i].pos+1) for i in ordered]))
        if ordered_blowup:
            with open(out_file+'.blowup', 'w') as f:
                f.write('\t'.join([self.variants[i].chrom + ',' + str(self.variants[i].pos+1) for i in ordered_blowup]))

    def rank_ambiguity(self, threshold=0.5):

        print('Counting kmers in ref')
        #time1 = time.time()
        self.count_kmers_ref()
        #time2 = time.time()
        #print('Ref counting time: %f m' % ((time2-time1)/60))
        print('Counting added kmers')
        self.count_kmers_added()
        #time3 = time.time()
        #print('Added counting time: %f m' % ((time3-time2)/60))

        print('Finished counting kmers')
        print('')

        self.avg_read_prob()
        #time4 = time.time()
        #print('Avg prob time: %f m' % ((time4-time3)/60))

        print('Computing ambiguities')
        if self.hap_parser:
            self.hap_parser.reset_chunk()

        var_wgts = [0] * self.num_v
        #for chrom, seq in self.genome.items():
        #    for var_id in range(self.num_v):
        #        if self.variants[var_id].chrom == chrom:
        #            break

        #    for i in range(len(seq) - self.r + 1):
        #        while var_id < self.num_v and self.variants[var_id].chrom == chrom and self.variants[var_id].pos < i:
        #            var_id += 1
        #        if var_id == self.num_v or not self.variants[var_id].chrom == chrom:
        #            break
        #        elif self.variants[var_id].pos < i+self.r:
        #            self.compute_ambiguity(chrom, i, var_id, var_wgts)

        for v in range(self.num_v):
            if v % 100000 == 0:
                print('Processing %d / %d variants' % (v, self.num_v))
            self.compute_ambiguity(v, var_wgts)

        with open('amb_wgts.txt', 'w') as f_amb:
            f_amb.write(','.join([str(w) for w in var_wgts]))
        
        #with open('amb_wgts.txt', 'r') as f_amb:
        #    var_wgts = [float(w) for w in f_amb.readline().rstrip().split(',')]

        var_ambs = [(var_wgts[i], i) for i in range(self.num_v)]
        var_ambs.sort()
        ordered = [v[1] for v in var_ambs]

        # Compute blowup ranking as well
        upper_tier = []
        lower_tier = []

        # Normalize weights to [0.01,1]
        var_wgts = [-w for w in var_wgts]
        min_wgt = min(var_wgts)
        range_wgts = max(var_wgts) - min_wgt
        for i in range(self.num_v):
            var_wgts[i] = (var_wgts[i] - min_wgt)*0.99 / range_wgts + 0.01


        for i in range(self.num_v):
            wgt = var_wgts[i]

            first = i
            last = i
            while first > 0 and self.variants[first-1].chrom == self.variants[i].chrom and (self.variants[i].pos - self.variants[first-1].pos) < self.r:
                first -= 1
            while last < (self.num_v-1) and self.variants[last+1].chrom == self.variants[i].chrom and (self.variants[last+1].pos - self.variants[i].pos) < self.r:
                last += 1
            neighbors = last - first

            if wgt > threshold:
                upper_tier.append((wgt, neighbors, i))
            else:
                lower_tier.append((wgt, neighbors, i))
        ordered_blowup = self.rank_dynamic_blowup(upper_tier, lower_tier)

        return ordered, ordered_blowup

    def compute_ambiguity(self, first_var, var_ambs):
        r = self.r
        chrom = self.variants[first_var].chrom
        pos = self.variants[first_var].pos

        #if self.variants[first_var].pos < pos or self.variants[first_var].pos >= pos+r:
        #    return

        # Number of variants in window starting at this one
        k = 1
        while first_var+k < self.num_v and self.variants[first_var+k].chrom == chrom and self.variants[first_var+k].pos < pos+r:
            k += 1

        #if k > 14:
        #    sys.stdout.write('Processing variant %d with %d neighbors' % (first_var, k))

        if k > self.max_v_in_window:
            alt_freqs = [(sum(self.variants[first_var+j].probs), first_var+j) for j in range(1, k)]
            ids = [first_var] + [f[1] for f in sorted(alt_freqs, reverse=True)[:self.max_v_in_window-1]]
            it = PseudocontigIterator(self.genome[chrom], [self.variants[v] for v in ids], self.r)
        else:
            ids = range(first_var, first_var+k)
            it = PseudocontigIterator(self.genome[chrom], self.variants[first_var:first_var+k], r)

        pseudocontig = it.next()
        while pseudocontig:
            vec = it.curr_vec

            p = self.prob_read(self.variants, ids, vec)
            for i in range(len(pseudocontig) - self.r + 1):
                mer = jellyfish.MerDNA(pseudocontig[i:i+r])
                mer.canonicalize()
                c_linear = self.h_ref[mer]
                if not c_linear:
                    c_linear = 0
                c_added = self.h_added[mer]
                if not c_added:
                    c_added = 0
                    if c_added == 0:
                        print('Error! Read %s from added pseudocontigs could not be found (SNPs %d - %d)' % (pseudocontig[i:i+r], first_var, first_var+k))
                        for j in range(first_var, first_var+k):
                            print('%s: %d, %s --> %s' % (self.variants[j].chrom, self.variants[j].pos, self.variants[j].orig, ','.join(self.variants[j].alts)))
                        exit()
                c_total = c_linear + c_added

                if c_total == 0:
                    print('Variants %d -%d / %d' % (first_var, first_var+k-1, self.num_v))
                    print('Vector:       ' + str(vec))
                    print('Pseudocontig: ' + str(pseudocontig))
                    print('Read:         ' + str(pseudocontig[i:i+r]))
                    exit()

                # Average relative probability of this read's other mappings
                avg_wgt = c_linear * self.wgt_ref + (c_added-1) * self.wgt_added
                amb_wgt = (p - avg_wgt) / (c_total)
                #for j in range(k):
                #    if vec[j]:
                #        #amb_added += p - (p / float(c_total))
                #        var_ambs[first_var+j] -= amb_wgt
                for j in range(len(ids)):
                    if vec[j]:
                        var_ambs[ids[j]] -= amb_wgt

            pseudocontig = it.next()

    def rank_pop_cov(self, with_blowup=False, threshold=0.5):
        if with_blowup:
            upper_tier = []
            lower_tier = []

            for i in range(self.num_v):
                wgt = sum(self.variants[i].probs)

                first = i
                last = i
                while first > 0 and self.variants[first-1].chrom == self.variants[i].chrom and (self.variants[i].pos - self.variants[first-1].pos) < self.r:
                    first -= 1
                while last < (self.num_v-1) and self.variants[last+1].chrom == self.variants[i].chrom and (self.variants[last+1].pos - self.variants[i].pos) < self.r:
                    last += 1
                neighbors = last - first

                if wgt > threshold:
                    upper_tier.append((wgt, neighbors, i))
                else:
                    lower_tier.append((wgt, neighbors, i))
            ordered = self.rank_dynamic_blowup(upper_tier, lower_tier)
        else:
            # Variant weight is the sum of frequencies of alternate alleles
            var_wgts = [(-sum(self.variants[i].probs), i) for i in range(self.num_v)]
            var_wgts.sort()
            ordered = [v[1] for v in var_wgts]

        return ordered

    def rank_dynamic_blowup(self, upper_tier, lower_tier, penalty=0.5):
        '''
        Variants in tiers should be tuples, each of the form (weight, # neighbors, index in self.variants) 
        penalty: Weight multiplier for each variant every time a nearby variant is added to the graph
        '''

        if not upper_tier and not lower_tier:
            return []

        threshold = penalty

        ordered = []
        tier_num = 0

        if not upper_tier:
            max_val = max(lower_tier)[0]
            while max_val <= threshold:
                threshold *= penalty
            upper_tier = []
            new_lower = []
            for i in range(len(lower_tier)):
                if lower_tier[i][0] > threshold:
                    upper_tier.append(lower_tier[i])
                else:
                    new_lower.append(lower_tier[i])
            lower_tier = new_lower[:]

        while upper_tier:
            upper_tier.sort(key=lambda x:(-x[0], x[1]))

            # Maps id in self.variants to id in upper/lower tier list
            vmap = [0] * self.num_v
            for i in range(len(upper_tier)):
                vmap[upper_tier[i][2]] = (0,i)
            for i in range(len(lower_tier)):
                vmap[lower_tier[i][2]] = (1,i)

            for var_id in range(len(upper_tier)):
                v = upper_tier[var_id]
                var = self.variants[v[2]]
                if v[0] < 0:
                    continue

                chrom = var.chrom
                pos = var.pos
                #ordered.append(str(pos+1))
                ordered.append(v[2])

                # Update other SNP weights
                first = v[2]
                last = first
                while first > 0 and self.variants[first-1].chrom == chrom and (pos - self.variants[first-1].pos) < self.r:
                    first -= 1
                while last < (self.num_v-1) and self.variants[last+1].chrom == chrom and (self.variants[last+1].pos - pos) < self.r:
                    last += 1

                if (last > first):
                    for j in range(first, last+1):
                        if j == v[2] or not vmap[j]:
                            continue

                        if vmap[j][0] == 0:
                            id = vmap[j][1]
                            if id <= var_id:
                                continue
                            lower_tier.append((upper_tier[id][0] * penalty, upper_tier[id][1], upper_tier[id][2]))
                            vmap[j] = (1, len(lower_tier)-1)
                            upper_tier[id] = (-1, upper_tier[id][1], upper_tier[id][2])
                        else:
                            id = vmap[j][1]
                            lower_tier[id] = (lower_tier[id][0] * penalty, lower_tier[id][1], lower_tier[id][2])

            if not lower_tier:
                break
            max_val = max(lower_tier)[0]
            if max_val > threshold:
                print('Error! Missed a point above threshold!')
                exit()
            while max_val <= threshold:
                threshold *= penalty
            upper_tier = []
            new_lower = []
            for i in range(len(lower_tier)):
                if lower_tier[i][0] > threshold:
                    upper_tier.append(lower_tier[i])
                else:
                    new_lower.append(lower_tier[i])
            lower_tier = new_lower[:]
        
        return ordered

def go(args):
    if args.window_size:
        r = args.window_size
    else:
        r = 35
    if args.output:
        o = args.output
    else:
        o = 'ordered.txt'
    if args.prune:
        max_v = args.prune
    else:
        max_v = r

    genome = io.read_genome(args.reference, args.chrom)

    vars = io.parse_1ksnp(args.vars)

    ranker = VarRanker(genome, vars, r, args.phasing, max_v)
    ranker.rank(args.method, o)


if __name__ == '__main__':

    if '--version' in sys.argv:
        print('ERG v' + VERSION)
        sys.exit(0)

    # Print file's docstring if -h is invoked
    parser = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument('--method', type=str, required=True,
        help='Variant ranking method. Currently supported ranking methods: [popcov | amb | hybrid | blowup | popcov-blowup]')
    parser.add_argument('--reference', type=str, required=True, 
        help='Path to fasta file containing reference genome')
    parser.add_argument("--vars", type=str, required=True,
        help="Path to 1ksnp file containing variant information")
    parser.add_argument('--chrom', type=str,
        help="Name of chromosome from reference genome to process. If not present, process all chromosomes.")
    parser.add_argument('--window-size', type=int,
        help="Radius of window (i.e. max read length) to use. Larger values will take longer. Default: 35")
    parser.add_argument('--phasing', type=str, required=False,
        help="Path to file containing phasing information for each individual")
    parser.add_argument('--output', type=str, required=False,
        help="Path to file to write output ranking to. Default: 'ordered.txt'")
    parser.add_argument('--prune', type=int, required=False,
        help='In each window, prune haplotypes by only processing up to this many variants. We recommend including this argument for window sizes over 35.')

    args = parser.parse_args(sys.argv[1:])
    go(args)
