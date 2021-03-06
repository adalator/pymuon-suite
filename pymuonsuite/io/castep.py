# Python 2-to-3 compatibility code
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import re
import os
import yaml
import numpy as np
import scipy.constants as cnst
from ase import Atoms
from ase import io
from ase.calculators.castep import Castep
from soprano.selection import AtomSelection


from pymuonsuite.utils import list_to_string
from pymuonsuite.utils import find_ipso_hydrogen


def save_muonconf_castep(a, folder, params):
    # Muon mass and gyromagnetic ratio
    mass_block = 'AMU\n{0}       0.1138'
    gamma_block = 'radsectesla\n{0}        851586494.1'

    if isinstance(a.calc, Castep):
        ccalc = a.calc
    else:
        ccalc = Castep(castep_command=params['castep_command'])

    ccalc.cell.kpoint_mp_grid.value = list_to_string(params['k_points_grid'])
    ccalc.cell.species_mass = mass_block.format(params['mu_symbol']
                                                ).split('\n')
    ccalc.cell.species_gamma = gamma_block.format(params['mu_symbol']
                                                  ).split('\n')
    ccalc.cell.fix_all_cell = True  # To make sure for older CASTEP versions

    a.set_calculator(ccalc)

    name = os.path.split(folder)[-1]
    io.write(os.path.join(folder, '{0}.cell'.format(name)), a)
    ccalc.atoms = a

    if params['castep_param'] is not '':
        castep_params = yaml.load(open(params['castep_param'], 'r'))
    else:
        castep_params = {}

    castep_params['task'] = "GeometryOptimization"

    # Parameters from .yaml will overwrite parameters from .param
    castep_params['geom_max_iter'] = params['geom_steps']
    castep_params['geom_force_tol'] = params['geom_force_tol']
    castep_params['max_scf_cycles'] = params['max_scc_steps']

    parameter_file = os.path.join(folder, '{0}.param'.format(name))
    yaml.safe_dump(castep_params, open(parameter_file, 'w'),
                   default_flow_style=False)

def parse_castep_masses(cell):
    """Parse CASTEP custom species masses, returning an array of all atom masses
    in .cell file with corrected custom masses.

    | Args:
    |   cell(ASE Atoms object): Atoms object containing relevant .cell file
    | Returns:
    |   masses(Numpy float array, shape(no. of atoms)): Correct masses of all
    |       atoms in cell file.
    """
    species_masses = cell.calc.cell.species_mass.value.split()
    custom_masses = {}
    #If no units given in species mass block
    if len(species_masses)%2 == 0:
        for i in range(0, len(species_masses), 2):
            custom_masses[species_masses[i]] = float(species_masses[i+1])
    #If units given in species mass block
    else:
        for i in range(1, len(species_masses), 2):
            custom_masses[species_masses[i]] = float(species_masses[i+1])

    masses = cell.get_masses()
    symbols = cell.get_array("castep_custom_species")
    for i, symbol1 in enumerate(symbols):
        for symbol2 in custom_masses:
            if symbol1 == symbol2:
                masses[i] = custom_masses[symbol2]

    return masses

def parse_castep_muon(cell, mu_sym, ignore_ipsoH):
    """Parse muon data from CASTEP cell file, returning
       the muon and ipso hydrogen index and muon mass.

    | Args:
    |   cell (ASE atoms object): ASE Atoms object containing CASTEP cell data
    |   mu_sym (str): Symbol used to represent muon
    |   ignore_ipsoH (bool): If true, do not find ipso hydrogen index
    | Returns:
    |   mu_index (int): Index of muon in cell file
    |   ipso_H_index (int): Index of ipso hydrogen in cell file
    |   mu_mass (float): Mass of muon in kg
    """
    # Get muon mass
    for i, item in enumerate(cell.calc.cell.species_mass.value.split()):
        if item == mu_sym:
            mu_mass = float(cell.calc.cell.species_mass.value.split()[i+1])
    mu_mass = mu_mass*cnst.u  # Convert to kg
    # Find muon index in structure array
    sel = AtomSelection.from_array(
        cell, 'castep_custom_species', mu_sym)
    mu_index = sel.indices[0]
    # Find ipso hydrogen location
    if not ignore_ipsoH:
        ipso_H_index = find_ipso_hydrogen(mu_index, cell, mu_sym)
    else:
        ipso_H_index = None

    return mu_index, ipso_H_index, mu_mass

def parse_castep_ppots(cfile):

    clines = open(cfile).readlines()

    # Find pseudopotential blocks
    ppot_heads = filter(lambda x: 'Pseudopotential Report' in x[1],
                        enumerate(clines))
    ppot_blocks_raw = []

    for pph in ppot_heads:
        i, _ = pph
        for j, l in enumerate(clines[i:]):
            if 'Author:' in l:
                break
        ppot_blocks_raw.append(clines[i:i+j])

    # Now on to actually parse them
    ppot_blocks = {}

    el_re = re.compile(r'Element:\s+([a-zA-Z]{1,2})\s+'
                       r'Ionic charge:\s+([0-9.]+)')
    rc_re = re.compile(r'(?:[0-9]+|loc)\s+[0-9]\s+[\-0-9.]+\s+([0-9.]+)')
    bohr = cnst.physical_constants['Bohr radius'][0]*1e10

    for ppb in ppot_blocks_raw:
        el = None
        q = None
        rcmin = np.inf
        for l in ppb:
            el_m = el_re.search(l)
            if el_m is not None:
                el, q = el_m.groups()
                q = float(q)
                continue
            rc_m = rc_re.search(l)
            if rc_m is not None:
                rc = float(rc_m.groups()[0])*bohr
                rcmin = min(rc, rcmin)
        ppot_blocks[el] = (q, rcmin)

    return ppot_blocks

def parse_final_energy(infile):
    """
    Parse final energy from .castep file

    | Args:
    |   infile (str): Directory of .castep file
    |
    | Returns:
    |   E (float): Value of final energy
    """
    E = None
    for l in open(infile).readlines():
        if "Final energy" in l:
            try:
                E = float(l.split()[3])
            except ValueError:
                raise RuntimeError(
                    "Corrupt .castep file found: {0}".format(infile))
    return E
