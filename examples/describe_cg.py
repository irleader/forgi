# coding: utf-8
from __future__ import print_function, absolute_import, division, unicode_literals
from builtins import (ascii, bytes, chr, dict, filter, hex, input,
                      map, next, oct, open, pow, range, round,
                      str, super, zip)



import argparse
from collections import defaultdict
import logging
import os.path

import pandas as pd

from logging_exceptions import log_to_exception

import forgi.utilities.commandline_utils as fuc
import forgi.threedee.model.descriptors as ftmd
import forgi.threedee.model.coarse_grain as ftmc
import forgi.threedee.utilities.vector as ftuv
import forgi.threedee.utilities.graph_pdb as ftug


log = logging.getLogger(__name__)

def generateParser():
    parser=fuc.get_rna_input_parser("Collect data about a list of rna files and store it as a csv.",
                                     nargs="+", rna_type="any", enable_logging=True)
    parser.add_argument("--csv", type=str, help="Store dataframe under this filename. (Prints to stdout if not given)")
    parser.add_argument("-k", "--keys", type=str, help="Only print the following properties. "
                                        "(A comma-seperated list of column headers, e.g. rog_vres")
    parser.add_argument("--angles", type=str, help="Store the angles between the given pairs of elements. Comma-seperated element tuples, seperated by colons. (e.g.: 's0,s1:s1,s2')")
    parser.add_argument("--distances", type=str, help="Store the distances between the given nucleotides. Comma-seperated nucleotide tuples, seperated by colons. (e.g.: '1,20:2,19')")
    parser.add_argument("--per-ml", action="store_true", help="Describe junction segments instead of the whole cg (one entry per segment)")
    parser.add_argument("--mode", type=str, help="For use with --csv. Either 'a' for append or 'o' for overwrite. Default: Abort if file exists.")

    return parser

def describe_rna(cg, file_num, dist_pais, angle_pairs):
    data={}
    data["nt_length"]=cg.seq_length
    data["num_cg_elems"]=len(cg.defines)
    for letter in "smifth":
        data["num_"+letter]=len([x for x in cg.defines if x[0] ==letter])
    multiloops = cg.find_mlonly_multiloops()
    descriptors = []
    junct3 = 0
    junct4 = 0
    for ml in multiloops:
        descriptors = cg.describe_multiloop(ml)
        if "regular_multiloop" in descriptors[-1]:
            if len(ml)==3:
                junct3+=1
            elif len(ml)==4:
                junct4+=1
    data["3-way-junctions"] = junct3
    data["4-way-junctions"] = junct4

    #print (descriptors)
    data["open_mls"] = len([d for d in descriptors if "open" in d])
    #print(data["open_mls"][-1])
    data["pseudoknots"] = len([d for d in descriptors if "pseudoknot" in d])
    data["regular_mls"] = len([d for d in descriptors if "regular_multiloop" in d])
    data["total_mls"] = len(multiloops)
    try:
        data["longest_ml"] = mmax(len(x) for x in multiloops)
    except ValueError:
        data["longest_ml"] = 0
    try:
        data["rog_fast"] = cg.radius_of_gyration("fast")
    except (ftmc.RnaMissing3dError, AttributeError):
        data["rog_fast"] = float("nan")
        data["rog_vres"] = float("nan")
        data["anisotropy_fast"] = float("nan")
        data["anisotropy_vres"] = float("nan")
        data["asphericity_fast"] = float("nan")
        data["asphericity_vres"] = float("nan")
    else:
        data["rog_vres"] = cg.radius_of_gyration("vres")
        data["anisotropy_fast"] = ftmd.anisotropy(cg.get_ordered_stem_poss())
        data["anisotropy_vres"] = ftmd.anisotropy(cg.get_ordered_virtual_residue_poss())
        data["asphericity_fast"] = ftmd.asphericity(cg.get_ordered_stem_poss())
        data["asphericity_vres"] = ftmd.asphericity(cg.get_ordered_virtual_residue_poss())
    for from_nt, to_nt in dist_pairs:
        try:
            dist = ftuv.vec_distance(cg.get_virtual_residue(int(from_nt), True),
                                     cg.get_virtual_residue(int(to_nt), True))
        except Exception as e:
            dist = float("nan")
            log.warning("%d%s File %s: Could not calculate distance between "
                        "%d and %d: %s occurred: %s", file_num,
                        {1:"st", 2:"nd", 3:"rd"}.get(file_num%10*(file_num%100 not in [11,12,13]), "th"),
                        cg.name, from_nt, to_nt, type(e).__name__, e)
        data["distance_{}_{}".format(from_nt, to_nt)] = dist
    for elem1, elem2 in angle_pairs:
        try:
            angle = ftuv.vec_angle(cg.coords.get_direction(elem1),
                                   cg.coords.get_direction(elem2))
        except Exception as e:
            angle = float("nan")
            log.warning("%d%s File %s: Could not calculate angle between "
                        "%s and %s: %s occurred: %s", file_num,
                        {1:"st", 2:"nd", 3:"rd"}.get(file_num%10*(file_num%100 not in [11,12,13]), "th"),
                        cg.name, elem1, elem2, type(e).__name__, e)
        data["angle_{}_{}".format(elem1, elem2)] = angle
    return data

def describe_ml_segments(cg):
    data = defaultdict(list)
    loops = cg.find_mlonly_multiloops()
    for loop in loops:
        description = cg.describe_multiloop(loop)
        for segment in loop:
            if segment[0] !="m":
                continue
            data["segment"].append(segment)
            data["junction_length"].append(len(loop))
            data["segment_length"].append(cg.get_length(segment))
            data["angle_type"].append(abs(cg.get_angle_type(segment, allow_broken = True)))
            s1, s2 = cg.connections(segment)
            data["angle_between_stems"].append( ftuv.vec_angle(cg.coords.get_direction(s1),
                                                               cg.coords.get_direction(s2)))
            data["junction_va_distance"].append(ftug.junction_virtual_atom_distance(cg, segment))
            data["is_external_multiloop"].append("open" in description)
            data["is_pseudoknotted_multiloop"].append("pseudoknot" in description)
            data["is_regular_multiloop"].append("regular_multiloop" in description)

    return data

parser = generateParser()
if __name__=="__main__":
    args = parser.parse_args()
    cgs, filenames = fuc.cgs_from_args(args, "+", "any", enable_logging=True, return_filenames=True)
    data = defaultdict(list)

    if args.distances:
        dist_pairs = str(args.distances).split(str(':'))
        dist_pairs = [ x.split(",") for x in dist_pairs]

    else:
        dist_pairs=[]
    if args.angles:
        angle_pairs = str(args.angles).split(str(":"))
        angle_pairs = [ x.split(",") for x in angle_pairs]
    else:
        angle_pairs = []
    for i, cg in enumerate(cgs):
        file_num = i+1
        log.info("Describing the %d%s cg %s", file_num, {1:"st", 2:"nd", 3:"rd"}.get(file_num%10*(file_num%100 not in [11,12,13]), "th"), cg.name)
        try:
            key = {"name":cg.name, "filename": filenames[i]}
            if args.per_ml:
                new_data = describe_ml_segments(cg)
                for i in range(len(new_data["segment"])):
                    for k,v in key.items():
                        data[k].append(v)
                    for k,v in new_data.items():
                        data[k].append(v[i])
            else:
                new_data = describe_rna(cg, file_num, dist_pairs, angle_pairs)
                for k,v in key.items():
                    data[k].append(v)
                for k,v in new_data.items():
                    data[k].append(v)
        except Exception as e:
            with log_to_exception(log, e):
                log.error("Error occurred during describing %d%s cg %s", file_num, {1:"st", 2:"nd", 3:"rd"}.get(file_num%10*(file_num%100 not in [11,12,13]), "th"), cg.name)
            raise
    if args.keys:
        allowed_keys = args.keys.split(",")+["name"]
        for key in list(data.keys()):
            if key not in allowed_keys:
                del data[key]
    df = pd.DataFrame(data)
    df.set_index("name", append=True, inplace=True)
    if args.csv:
        if not args.mode and os.path.isfile(args.csv):
            raise  RuntimeError("File {} exists already.".format(args.csv))
        if not args.mode or args.mode=='o':
            df.to_csv(args.csv)
        elif args.mode=='a':
            df.to_csv(args.csv, mode='a')
        else:
            raise ValueError("Mode must be one of 'a' and 'o'")
    else:
        pd.set_option('max_columns', 99)
        pd.set_option('max_rows', 200)

        print(df)
