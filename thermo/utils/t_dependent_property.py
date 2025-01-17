# -*- coding: utf-8 -*-
'''Chemical Engineering Design Library (ChEDL). Utilities for process modeling.
Copyright (C) 2016, 2017, 2018, 2019, 2020 Caleb Bell <Caleb.Andrew.Bell@gmail.com>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.'''

from __future__ import division

__all__ = ['TDependentProperty',]

import os
try:
    from random import uniform
except: # pragma: no cover
    pass
from fluids.numerics import (quad, brenth, secant, linspace, 
                             polyint, polyint_over_x, derivative, 
                             polyder, horner, numpy as np, curve_fit, 
                             differential_evolution, fit_minimization_targets, 
                             leastsq)
import chemicals
from chemicals.utils import isnan, log, e, hash_any_primitive
from chemicals.vapor_pressure import (Antoine, Antoine_AB_coeffs_from_point,
                                      DIPPR101_ABC_coeffs_from_point, 
                                      Yaws_Psat_fitting_jacobian, 
                                      d2Yaws_Psat_dT2, dYaws_Psat_dT, 
                                      Yaws_Psat, TDE_PVExpansion,
                                      Wagner, Wagner_original, 
                                      TRC_Antoine_extended, 
                                      dAntoine_dT, d2Antoine_dT2, 
                                      dWagner_original_dT, d2Wagner_original_dT2, 
                                      dWagner_dT, d2Wagner_dT2, 
                                      dTRC_Antoine_extended_dT, 
                                      d2TRC_Antoine_extended_dT2, 
                                      Wagner_fitting_jacobian, 
                                      Wagner_original_fitting_jacobian, 
                                      Antoine_fitting_jacobian)
from chemicals.dippr import EQ100, EQ101, EQ102, EQ104, EQ105, EQ106, EQ107, EQ114, EQ115, EQ116, EQ127, EQ102_fitting_jacobian, EQ101_fitting_jacobian, EQ106_fitting_jacobian, EQ105_fitting_jacobian, EQ107_fitting_jacobian
from chemicals.phase_change import Watson, Watson_n, Alibakhshi, PPDS12
from chemicals.viscosity import (Viswanath_Natarajan_2, Viswanath_Natarajan_2_exponential,
                                 Viswanath_Natarajan_3, PPDS9, dPPDS9_dT,
                                 mu_Yaws, dmu_Yaws_dT,
                                 PPDS5, mu_TDE)
from chemicals.heat_capacity import (Poling, Poling_integral, Poling_integral_over_T,
                                     TRCCp, TRCCp_integral, TRCCp_integral_over_T,
                                     Zabransky_quasi_polynomial, Zabransky_quasi_polynomial_integral, Zabransky_quasi_polynomial_integral_over_T,
                                     Zabransky_cubic, Zabransky_cubic_integral, Zabransky_cubic_integral_over_T)
from chemicals.thermal_conductivity import Chemsep_16, PPDS8, PPDS3
from chemicals.interface import REFPROP_sigma, Somayajulu, Jasper, PPDS14, Watson_sigma, ISTExpansion
from chemicals.volume import volume_VDI_PPDS, Rackett_fit, PPDS17, TDE_VDNS_rho
from thermo.eos_alpha_functions import (Twu91_alpha_pure, Soave_1979_alpha_pure,
                                        Soave_1972_alpha_pure, Heyen_alpha_pure,
                                        Harmens_Knapp_alpha_pure, Mathias_1983_alpha_pure,
                                        Mathias_Copeman_untruncated_alpha_pure,
                                        Gibbons_Laughton_alpha_pure, Soave_1984_alpha_pure,
                                        Yu_Lu_alpha_pure, Trebble_Bishnoi_alpha_pure,
                                        Melhem_alpha_pure, Androulakis_alpha_pure,
                                        Schwartzentruber_alpha_pure, Almeida_alpha_pure,
                                        Soave_1993_alpha_pure, Gasem_alpha_pure,
                                        Coquelet_alpha_pure, Haghtalab_alpha_pure,
                                        Saffari_alpha_pure, Chen_Yang_alpha_pure)
from thermo.eos import GCEOS
from thermo.coolprop import coolprop_fluids
from thermo.fitting import data_fit_statistics
from math import inf
import thermo
from thermo.utils import VDI_TABULAR, POLY_FIT, has_matplotlib


def generate_fitting_function(model,
                              param_order,
                              fit_parameters,
                              all_fit_parameters,
                              optional_kwargs,
                              const_kwargs,
                              try_numba=True,
                              jac=False):
    '''Private function to create a fitting objective function for
    consumption by curve_fit. Other minimizers will require a different
    objective function.
    '''
    if jac:
        model_jac_name = model + '_fitting_jacobian'
    for mod in (chemicals, thermo):
        # Try to find the fitting function in thermo and chemicals
        # most are in chemicals so we try it first
        try:
            if try_numba:
                # Reasons to write a custom accelerating wrapper:
                # 1) ufuncs with numba are 1.5-2x slower than expected
                # 2) optional arguments are not supported, which is an issue for many
                # models which default to zero coefficients
                try:
                    if jac:
                        f = getattr(mod.numba, model_jac_name)
                    else:
                        f = getattr(mod.numba_vectorized, model)
                except:
                    if jac:
                        f = getattr(mod, model_jac_name)
                    else:
                        f = getattr(mod.vectorized, model)
            else:
                if jac:
                    f = getattr(mod, model_jac_name)
                else:
                    f = getattr(mod.vectorized, model)
        except:
            pass

    # arg_dest_idxs is a list of indexes for each parameter
    # to be transformed into the output array
    arg_dest_idxs = []
    
    # reusable_args is a mutable list of arguments to be passed to the
    # function which is being fit
    reusable_args = []
    for i, n in enumerate(param_order):
        if n in optional_kwargs:
            reusable_args.append(optional_kwargs[n])
        elif n in const_kwargs:
            reusable_args.append(const_kwargs[n])
        elif n in fit_parameters:
            reusable_args.append(1.0)
            arg_dest_idxs.append(i)
        else:
            reusable_args.append(0.0)
    if not jac and model.startswith('EQ'):
        # Handle the DIPPR equations that have the DIPPR equation in them
        reusable_args.append(0)
    if jac:
        jac_skip_row_idxs = []
        for i, k in enumerate(all_fit_parameters):
            if k not in fit_parameters:
                jac_skip_row_idxs.append(i)
        if jac_skip_row_idxs:
            jac_skip_row_idxs = np.array(jac_skip_row_idxs)
            #for k in fit_parameters:
            def fitting_function(Ts, *args):
                for i, v in enumerate(args):
                    reusable_args[arg_dest_idxs[i]] = v
                out = f(Ts, *reusable_args)
                return np.delete(out, jac_skip_row_idxs, axis=1)
        else:
            def fitting_function(Ts, *args):
                for i, v in enumerate(args):
                    reusable_args[arg_dest_idxs[i]] = v
                return f(Ts, *reusable_args)
    else:
        def fitting_function(Ts, *args):
            ld = arg_dest_idxs
            for i, v in enumerate(args):
                reusable_args[ld[i]] = v
            return f(Ts, *reusable_args)
    return fitting_function

def create_local_method(f, f_der, f_der2, f_der3, f_int, f_int_over_T):
    if callable(f):
        return LocalMethod(f, f_der, f_der2, f_der3, f_int, f_int_over_T)
    else:
        try: 
            value = float(f)
        except:
            raise ValueError("`f` must be either a callable or a number")
        if not all([i is None for i in (f_der, f_der2, f_der3, f_int, f_int_over_T)]):
            raise ValueError("cannot define derivatives and integrals "
                             "when `f` is a number")
        return ConstantLocalMethod(value)

class LocalMethod:
    __slots__ = ('f', 'f_der', 'f_der2', 'f_der3', 'f_int', 'f_int_over_T')
    
    def __init__(self, f, f_der, f_der2, f_der3, f_int, f_int_over_T):
        self.f = f
        self.f_der = f_der
        self.f_der2 = f_der2
        self.f_der3 = f_der3
        self.f_int = f_int
        self.f_int_over_T = f_int_over_T


class ConstantLocalMethod:
    __slots__ = ('value',)
    
    def __init__(self, value):
        self.value = value
        
    def f(self, T):
        return self.value
      
    def f_der(self, T):
        return 0.
    
    def f_der2(self, T):
        return 0.
    
    def f_der3(self, T):
        return 0.
        
    def f_int(self, Ta, Tb):
        return self.value * (Tb - Ta)

    def f_int_over_T(self, Ta, Tb):
        return self.value * log(Tb/Ta)


class TDependentProperty(object):
    '''Class for calculating temperature-dependent chemical properties.

    On creation, a :obj:`TDependentProperty` examines all the possible methods
    implemented for calculating the property, loads whichever coefficients it
    needs (unless `load_data` is set to False), examines its input parameters,
    and selects the method it prefers. This method will continue to be used for
    all calculations until the method is changed by setting a new method
    to the to :obj:`method` attribute.

    The default list of preferred method orderings is at :obj:`ranked_methods`
    for all properties; the order can be modified there in-place, and this
    will take effect on all new :obj:`TDependentProperty` instances created
    but NOT on existing instances.

    All methods have defined criteria for determining if they are valid before
    calculation, i.e. a minimum and maximum temperature for coefficients to be
    valid. For constant property values used due to lack of
    temperature-dependent data, a short range is normally specified as valid.

    It is not assumed that a specified method will succeed; for example many
    expressions are not mathematically valid past the critical point, and in
    some cases there is no easy way to determine the temperature where a
    property stops being reasonable.

    Accordingly, all properties calculated are checked
    by a sanity function :obj:`test_property_validity <TDependentProperty.test_property_validity>`,
    which has basic sanity checks. If the property is not reasonable, None is
    returned.

    This framework also supports tabular data, which is interpolated from if
    specified. Interpolation is cubic-spline based if 5 or more points are
    given, and linearly interpolated with if few points are given. A transform
    may be applied so that a property such as
    vapor pressure can be interpolated non-linearly. These are functions or
    lambda expressions which are set for the variables :obj:`interpolation_T`,
    :obj:`interpolation_property`, and :obj:`interpolation_property_inv`.

    In order to calculate properties outside of the range of their correlations,
    a number of extrapolation method are available. Extrapolation is used by
    default on some properties but not all.
    The extrapolation methods available are as follows:

        * 'constant' - returns the model values as calculated at the temperature limits
        * 'linear' - fits the model at its temperature limits to a linear model
        * 'interp1d' - SciPy's :obj:`interp1d <scipy.interpolate.interp1d>` is used to extrapolate
        * 'AntoineAB' - fits the model to :obj:`Antoine <chemicals.vapor_pressure.Antoine>`'s
          equation at the temperature limits using only the A and B coefficient
        * 'DIPPR101_ABC' - fits the model at its temperature limits to the
          :obj:`EQ101 <chemicals.dippr.EQ101>` equation
        * 'Watson' - fits the model to the Heat of Vaporization model
          :obj:`Watson <chemicals.phase_change.Watson>`

    It is possible to use different extrapolation methods for the
    low-temperature and the high-temperature region. Specify the extrapolation
    parameter with the '|' symbols between the two methods; the first method
    is used for low-temperature, and the second for the high-temperature.

    Attributes
    ----------
    name : str
        The name of the property being calculated, [-]
    units : str
        The units of the property, [-]
    method : str
        The method to be used for property calculations, [-]
    interpolation_T : callable or None
        A function or lambda expression to transform the temperatures of
        tabular data for interpolation; e.g. 'lambda self, T: 1./T'
    interpolation_T_inv : callable or None
        A function or lambda expression to invert the transform of temperatures
        of tabular data for interpolation; e.g. 'lambda self, x: self.Tc*(1 - x)'
    interpolation_property : callable or None
        A function or lambda expression to transform tabular property values
        prior to interpolation; e.g. 'lambda self, P: log(P)'
    interpolation_property_inv : callable or None
        A function or property expression to transform interpolated property
        values from the transform performed by :obj:`interpolation_property` back
        to their actual form, e.g.  'lambda self, P: exp(P)'
    Tmin : float
        Maximum temperature at which no method can calculate the property above;
        set based on rough rules for some methods. Used to solve for a
        particular property value, and as a default minimum for plotting. Often
        higher than where the property is theoretically higher, i.e. liquid
        density above the triple point, but this information may still be
        needed for liquid mixtures with elevated critical points.
    Tmax : float
        Minimum temperature at which no method can calculate the property under;
        set based on rough rules for some methods. Used to solve for a
        particular property value, and as a default minimum for plotting. Often
        lower than where the property is theoretically higher, i.e. liquid
        density beneath the triple point, but this information may still be
        needed for subcooled liquids or mixtures with depressed freezing points.
    property_min : float
        Lowest value expected for a property while still being valid;
        this is a criteria used by :obj:`test_method_validity`.
    property_max : float
        Highest value expected for a property while still being valid;
        this is a criteria used by :obj:`test_method_validity`.
    ranked_methods : list
        Constant list of ranked methods by default
    tabular_data : dict
        Stores all user-supplied property data for interpolation in format
        {name: (Ts, properties)}, [-]
    tabular_data_interpolators : dict
        Stores all interpolation objects, idexed by name and property
        transform methods with the format {(name, interpolation_T,
        interpolation_property, interpolation_property_inv):
        (extrapolator, spline)}, [-]
    all_methods : set
        Set of all methods available for a given CASRN and set of properties,
        [-]
    '''
    RAISE_PROPERTY_CALCULATION_ERROR = False
    
    def __init_subclass__(cls):
        cls.__full_path__ = "%s.%s" %(cls.__module__, cls.__qualname__)
    
    # Dummy properties
    name = 'Property name'
    units = 'Property units'

    interpolation_T = None
    interpolation_T_inv = None
    interpolation_property = None
    interpolation_property_inv = None

    tabular_extrapolation_pts = 20
    '''The number of points to calculate at and use when doing a tabular
    extrapolation calculation.'''

    interp1d_extrapolate_kind = 'linear'
    '''The `kind` parameter for scipy's interp1d function,
    when it is used for extrapolation.'''

    P_dependent = False
    forced = False

    property_min = 0
    property_max = 1E4  # Arbitrary max

    T_limits = {}
    '''Dictionary containing method: (Tmin, Tmax) pairs for all methods applicable
    to the chemical'''

    critical_zero = False
    '''Whether or not the property is declining and reaching zero at the
    critical point. This is used by numerical solvers.'''

    ranked_methods = []

    _fit_force_n = {}
    '''Dictionary containing method: fit_n, for use in methods which should
    only ever be fit to a specific `n` value'''

    _fit_max_n = {}
    '''Dictionary containing method: max_n, for use in methods which should
    only ever be fit to a `n` value equal to or less than `n`'''

    pure_references = ()
    pure_reference_types = ()

    obj_references = ()
    obj_references_types = ()

    _json_obj_by_CAS = ('CP_f',)
    
    correlation_models = {
        'Antoine': (['A', 'B', 'C'], [], {'f': Antoine, 'f_der': dAntoine_dT, 'f_der2': d2Antoine_dT2}, 
                    {'fit_params': ['A', 'B', 'C'],
                     'fit_jac' : Antoine_fitting_jacobian,
                    'initial_guesses': [{'A': 9.0, 'B': 1000.0, 'C': -70.0},
                                        {'A': 9.1, 'B': 1450.0, 'C': -60.0},
                                        {'A': 8.1, 'B': 77.0, 'C': 2.5},
                                        {'A': 138., 'B': 520200.0, 'C': 3670.0}, # important point for heavy compounds
                                        {'A': 12.852, 'B': 2943.0, 'C': 0.0}, # Zero C and low range point
                                        {'A': 21.7, 'B': 10700.0, 'C': 0.0}, # Zero C and low range point
                                        {'A': 14.3, 'B': 14500.0, 'C': -28.3},
                                        {'A': -5.3, 'B': 3750.0, 'C': -920.0},
                                        {'A': 9.0, 'B': 870.0, 'C': -37.8},
                                        {'A': 7.1, 'B': 217.0, 'C': -139.0},
                        ]}),
                
        'TRC_Antoine_extended': (['Tc', 'to', 'A', 'B', 'C', 'n', 'E', 'F'], [],
                                 {'f': TRC_Antoine_extended, 'f_der': dTRC_Antoine_extended_dT, 'f_der2': d2TRC_Antoine_extended_dT2},
                                 {'fit_params': ['to', 'A', 'B', 'C', 'n', 'E', 'F'],
                                  'initial_guesses': [
                                      {'to': 3.0, 'A': 8.9, 'B': 933., 'C': -33., 'n': 2.25, 'E': -55., 'F': 3300.0},
                                      {'to': -76.0, 'A': 8.9, 'B': 650., 'C': -23., 'n': 2.5, 'E': 63.0, 'F': -2130.},
                                       {'to': 170.0, 'A': 9., 'B': 1500.0, 'C': -66.0, 'n': 2.2, 'E': 0.0, 'F': 0.0},
                                       {'to': 120.0, 'A': 9., 'B': 1310., 'C': -58.0, 'n': 2.0, 'E': -350, 'F': 53000.0},
                                       {'to': 38.0, 'A': 8.97, 'B': 1044., 'C': -40.0, 'n': 2.6, 'E': 123., 'F': -4870.},
                                       {'to': -53.0, 'A': 9.0, 'B': 731.0, 'C': -27.5, 'n': 2.4, 'E': 4.1, 'F': 942.0},
                                       {'to': 197.0, 'A': 9.41, 'B': 1693.0, 'C': -72.7, 'n': 4.9, 'E': 453.0, 'F': -239100.0},
                                       {'to': 72.0, 'A': 9.0, 'B': 1162, 'C': -45, 'n': 5.75, 'E': 691.0, 'F': -40240.0},
                                       {'to': 87.0, 'A': 9.14, 'B': 1232., 'C': -54.5, 'n': 2.3, 'E': -5, 'F': 3280.0},
                                       {'to': 67.0, 'A': 8.94, 'B': 1130, 'C': -44., 'n': 2.5, 'E': 333.0, 'F': -24950.0},
                                       {'to': -120.0, 'A': 8.96, 'B': 510.6, 'C': -15.95, 'n': 2.41, 'E': -94.0, 'F': 7426.0},
                                       {'to': -20.0, 'A': 9.12, 'B': 850.9, 'C': -40.2, 'n': 2.4, 'E': 31.1, 'F': 2785.0},
                                       {'to': -9.0, 'A': 8.4, 'B': 640.3, 'C': -69., 'n': 1.0, 'E': 190.0, 'F': -6600.0},
                                      ]}),
        
        'Wagner_original': (['Tc', 'Pc', 'a', 'b', 'c', 'd'], [], {'f': Wagner_original, 'f_der': dWagner_original_dT, 'f_der2': d2Wagner_original_dT2},
                            {'fit_params': ['a', 'b', 'c', 'd'],
                             'fit_jac': Wagner_original_fitting_jacobian,
                                    'initial_guesses': [
                                        {'a': -7.0, 'b': 1.79, 'c': -5.4, 'd': 1.68},
                                        {'a': -7.2, 'b': -0.02, 'c': 0.36, 'd': -11.0},
                                        
                                        ]
                            }),
        
        'Wagner': (['Tc', 'Pc', 'a', 'b', 'c', 'd'], [], {'f': Wagner, 'f_der': dWagner_dT, 'f_der2': d2Wagner_dT2},
                   {'fit_params': ['a', 'b', 'c', 'd'],
                    'fit_jac': Wagner_fitting_jacobian,
                    'initial_guesses': [
                        {'a': -8.5, 'b': 2.0, 'c': -7.7, 'd': 3.0},
                        {'a': -7.8, 'b': 1.9, 'c': -2.85, 'd': -3.8},
                        {'a': -7.55, 'b': 1.6, 'c': -2.0, 'd': -3.2},
                        ]
                    }),
        
        'Yaws_Psat': (['A', 'B', 'C', 'D', 'E'], [], {'f': Yaws_Psat, 'f_der': dYaws_Psat_dT, 'f_der2': d2Yaws_Psat_dT2},
                   {'fit_params': ['A', 'B', 'C', 'D', 'E'],
                    'fit_jac': Yaws_Psat_fitting_jacobian,
                    'initial_guesses': [
                        {'A': 30.94, 'B': -4162., 'C': -6.78, 'D': -1.09e-9, 'E': 6.4e-07},
                        {'A': 48.3, 'B': -4605., 'C': -12.8, 'D': 1.66e-10, 'E': 2.546e-06},
                        {'A': 16.8, 'B': -571., 'C': -3.338, 'D': 2.2e-9, 'E': 1.31e-05},
                        ]
                    }),
    'TDE_PVExpansion': (['a1', 'a2', 'a3'], ['a4', 'a5', 'a6', 'a7', 'a8'], {'f': TDE_PVExpansion},
                        {'fit_params': ['a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7', 'a8'],
                        'initial_guesses': [
                        {'a1': 48.3, 'a2': -4914.12, 'a3': -3.788947, 'a4': 0, 'a5': 0, 'a6': 0, 'a7': 0, 'a8': 0},
                        ]}),


    'Alibakhshi': (['Tc', 'C'], [], {'f': Alibakhshi}, {'fit_params': ['C']}),
    'PPDS12': (['Tc', 'A', 'B', 'C', 'D', 'E'], [], {'f': PPDS12}, {'fit_params': ['A', 'B', 'C', 'D', 'E']}),
    'Watson': (['Hvap_ref', 'T_ref', 'Tc'], ['exponent'], {'f': Watson}, {'fit_params': ['Hvap_ref', 'T_ref']}),

    'Viswanath_Natarajan_2': (['A', 'B',], [], {'f': Viswanath_Natarajan_2}, {'fit_params': ['A', 'B']}),
    'Viswanath_Natarajan_2_exponential': (['C', 'D',], [], {'f': Viswanath_Natarajan_2_exponential}, {'fit_params': ['C', 'D',]}),
    'Viswanath_Natarajan_3': (['A', 'B', 'C'], [], {'f': Viswanath_Natarajan_3}, {'fit_params': ['A', 'B', 'C']}),
    'PPDS5': (['Tc', 'a0', 'a1', 'a2'], [], {'f': PPDS5}, {'fit_params': ['a0', 'a1', 'a2']},),
    'mu_TDE': (['A', 'B', 'C', 'D'], [], {'f': mu_TDE}, {'fit_params': ['A', 'B', 'C', 'D']},),

    'PPDS9': (['A', 'B', 'C', 'D', 'E'], [], {'f': PPDS9, 'f_der': dPPDS9_dT}, {'fit_params': ['A', 'B', 'C', 'D', 'E']},),
    'mu_Yaws': (['A', 'B',], ['C', 'D'], {'f': mu_Yaws, 'f_der': dmu_Yaws_dT}, {'fit_params': ['A', 'B', 'C', 'D'], 'initial_guesses': [
        {'A': -9.45, 'B': 1120.0, 'C': 0.014, 'D': -1.545e-5}, # near yaws ethanol
        {'A': -25.5319, 'B': 3747.19, 'C': 0.04659, 'D': -0.0}, # near yaws 1-phenyltetradecane
                                                                                ]},),
    

    'Poling': (['a', 'b', 'c', 'd', 'e'], [], {'f': Poling, 'f_int': Poling_integral, 'f_int_over_T': Poling_integral_over_T}, {'fit_params': ['a', 'b', 'c', 'd', 'e']},),
    'TRCCp': (['a0', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7'], [], {'f': TRCCp, 'f_int': TRCCp_integral, 'f_int_over_T': TRCCp_integral_over_T},
              {'fit_params': ['a0', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7']}),
    'Zabransky_quasi_polynomial': (['Tc', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6'], [], {'f': Zabransky_quasi_polynomial, 'f_int': Zabransky_quasi_polynomial_integral,
                                                                                    'f_int_over_T': Zabransky_quasi_polynomial_integral_over_T}, 
                                   {'fit_params': ['a1', 'a2', 'a3', 'a4', 'a5', 'a6']}),
    'Zabransky_cubic': (['a1', 'a2', 'a3', 'a4'], [], 
                        {'f': Zabransky_cubic, 'f_int': Zabransky_cubic_integral, 'f_int_over_T': Zabransky_cubic_integral_over_T}, 
                        {'fit_params': ['a1', 'a2', 'a3', 'a4']}),

    'REFPROP_sigma': (['Tc', 'sigma0', 'n0'], ['sigma1', 'n1', 'sigma2', 'n2'], {'f': REFPROP_sigma},  {'fit_params': ['sigma0', 'n0', 'sigma1', 'n1', 'sigma2', 'n2']}),
    'Somayajulu': (['Tc', 'A', 'B', 'C'], [], {'f': Somayajulu}, {'fit_params': ['A', 'B', 'C']}),
    'Jasper': (['a', 'b',], [], {'f': Jasper}, {'fit_params': ['a', 'b',]}),
    'PPDS14': (['Tc', 'a0', 'a1', 'a2'], [], {'f': PPDS14}, {'fit_params': ['a0', 'a1', 'a2']}),
    'Watson_sigma': (['Tc', 'a1', 'a2', 'a3', 'a4', 'a5'], [], {'f': Watson_sigma}, {'fit_params': [ 'a1', 'a2', 'a3', 'a4', 'a5']}),
    'ISTExpansion': (['Tc', 'a1', 'a2', 'a3', 'a4', 'a5'], [], {'f': ISTExpansion}, {'fit_params': [ 'a1', 'a2', 'a3', 'a4', 'a5']}),

    'Chemsep_16': (['A', 'B', 'C', 'D', 'E'], [], {'f': Chemsep_16}, {'fit_params': ['A', 'B', 'C', 'D', 'E'], 'initial_guesses': [
           {'A': 53000, 'B': 4500.0, 'C': -145.0, 'D': 1.6, 'E':-0.005}, 
           {'A': -0.21, 'B': -16.3, 'C': -0.23, 'D': -0.0076, 'E': 2.5e-6}, 
           {'A': 2.562e-06, 'B': -300.363, 'C': -11.49, 'D': 0.001550, 'E': -4.0805e-07}, 
           {'A': 81911, 'B': -50003, 'C': 534.5, 'D': -1.8654, 'E':  0.00223}, 
           {'A': -0.193, 'B':-0.885, 'C':  -0.8363, 'D': -0.191, 'E':  0.01686}, 
           {'A': 56031.0, 'B': -8382.1, 'C': 267.49, 'D': -2.7228, 'E': 0.0096889},
           {'A': 0.14679, 'B': 201570.0, 'C': -2097.5, 'D': 7.255, 'E': -0.0083973},
           {'A': 29103.63, 'B': -2305.946, 'C': 11.31935, 'D': -0.00100557, 'E': 1.706099e-07},
           {'A': 29546.0, 'B': -3.2521, 'C': 11.386, 'D': 0.0045932, 'E': -3.5582e-06},
           {'A': -181030.0, 'B': 9.3832, 'C': 12.233, 'D': 0.00079415, 'E': -2.4738e-07},
           {'A': -0.869, 'B': 15.0, 'C': 0.0, 'D': 0.0, 'E': 0.0},
           ]},),
    'PPDS8': (['Tc', 'a0', 'a1', 'a2', 'a3'], [], {'f': PPDS8, }, {'fit_params': ['a0', 'a1', 'a2', 'a3'], 'initial_guesses': [
           ]},),
    'PPDS3': (['Tc', 'a1', 'a2', 'a3'], [], {'f': PPDS3, }, {'fit_params': ['a1', 'a2', 'a3'], 'initial_guesses': [
           ]},),
    
    'TDE_VDNS_rho': (['Tc', 'rhoc', 'a1', 'a2', 'a3', 'a4', 'MW',], [], {'f': TDE_VDNS_rho}, {'fit_params': ['a1', 'a2', 'a3', 'a4',]}),
    'PPDS17': (['Tc', 'a0', 'a1', 'a2', 'MW',], [], {'f': PPDS17}, {'fit_params': ['a0', 'a1', 'a2', ]}),

    'volume_VDI_PPDS': (['Tc', 'rhoc', 'a', 'b', 'c', 'd', 'MW',], [], {'f': volume_VDI_PPDS}, {'fit_params': ['a', 'b', 'c', 'd',]}),
    'Rackett_fit': (['Tc', 'rhoc', 'b', 'n', 'MW',], [], {'f': Rackett_fit}, {'fit_params': ['rhoc', 'b', 'n'], 'initial_guesses': [
        {'n': 0.286, 'b': 0.011, 'rhoc': 28.93}, # near a point from yaws
        {'n': 0.286, 'b': 0.3, 'rhoc': 755.0}, # near a point from yaws
        {'n': 0.259, 'b': 0.233, 'rhoc': 433.1}, # near a point from yaws
        {'n': 0.159, 'b': 0.965, 'rhoc': 1795.0},# near a point from yaws 
        {'n': 0.28571, 'b': 0.3, 'rhoc': 740.0}, # near a point from yaws
        {'n': 0.8, 'b': 0.647, 'rhoc': 2794.6}, # near a point from yaws
        ]}),    
    
    # Plain polynomial
    'DIPPR100': ([],
      ['A', 'B', 'C', 'D', 'E', 'F', 'G'],
      {'f': EQ100,
       'f_der': lambda T, **kwargs: EQ100(T, order=1, **kwargs),
       'f_int': lambda T, **kwargs: EQ100(T, order=-1, **kwargs),
       'f_int_over_T': lambda T, **kwargs: EQ100(T, order=-1j, **kwargs)},
      {'fit_params': ['A', 'B', 'C', 'D', 'E', 'F', 'G'],
       'initial_guesses': [
           {'A': 1.0, 'B': 0.0, 'C': 0.0, 'D': 0.0, 'E': 0.0, 'F': 0.0, 'G': 0.0},
           {'A': 0.0, 'B': 1.0, 'C': 0.0, 'D': 0.0, 'E': 0.0, 'F': 0.0, 'G': 0.0},
           {'A': 0.0, 'B': 0.0, 'C': 1.0, 'D': 0.0, 'E': 0.0, 'F': 0.0, 'G': 0.0},
           {'A': 0.0, 'B': 0.0, 'C': 0.0, 'D': 1.0, 'E': 0.0, 'F': 0.0, 'G': 0.0},
           {'A': 0.0, 'B': 0.0, 'C': 0.0, 'D': 0.0, 'E': 1.0, 'F': 0.0, 'G': 0.0},
           {'A': 0.0, 'B': 0.0, 'C': 0.0, 'D': 0.0, 'E': 0.0, 'F': 1.0, 'G': 1.0},
           ]},
      ),
    'constant': ([],
      ['A'],
      {'f': EQ100,
       'f_der': lambda T, **kwargs: EQ100(T, order=1, **kwargs),
       'f_int': lambda T, **kwargs: EQ100(T, order=-1, **kwargs),
       'f_int_over_T': lambda T, **kwargs: EQ100(T, order=-1j, **kwargs)},
      {'fit_params': ['A']},
      ),
    'linear': ([],
      ['A', 'B'],
      {'f': EQ100,
       'f_der': lambda T, **kwargs: EQ100(T, order=1, **kwargs),
       'f_int': lambda T, **kwargs: EQ100(T, order=-1, **kwargs),
       'f_int_over_T': lambda T, **kwargs: EQ100(T, order=-1j, **kwargs)},
      {'fit_params': ['A', 'B']},
      ),
    'quadratic': ([],
      ['A', 'B', 'C'],
      {'f': EQ100,
       'f_der': lambda T, **kwargs: EQ100(T, order=1, **kwargs),
       'f_int': lambda T, **kwargs: EQ100(T, order=-1, **kwargs),
       'f_int_over_T': lambda T, **kwargs: EQ100(T, order=-1j, **kwargs)},
      {'fit_params': ['A', 'B', 'C']},
      ),
    'cubic': ([],
      ['A', 'B', 'C', 'D'],
      {'f': EQ100,
       'f_der': lambda T, **kwargs: EQ100(T, order=1, **kwargs),
       'f_int': lambda T, **kwargs: EQ100(T, order=-1, **kwargs),
       'f_int_over_T': lambda T, **kwargs: EQ100(T, order=-1j, **kwargs)},
      {'fit_params': ['A', 'B', 'C', 'D']},
      ),
    'quintic': ([],
      ['A', 'B', 'C', 'D', 'E'],
      {'f': EQ100,
       'f_der': lambda T, **kwargs: EQ100(T, order=1, **kwargs),
       'f_int': lambda T, **kwargs: EQ100(T, order=-1, **kwargs),
       'f_int_over_T': lambda T, **kwargs: EQ100(T, order=-1j, **kwargs)},
      {'fit_params': ['A', 'B', 'C', 'D', 'E']},
      ),
     'DIPPR101': (['A', 'B'],
      ['C', 'D', 'E'],
      {'f': EQ101,
       'f_der': lambda T, **kwargs: EQ101(T, order=1, **kwargs),
       'f_der2': lambda T, **kwargs: EQ101(T, order=2, **kwargs),
       'f_der3': lambda T, **kwargs: EQ101(T, order=3, **kwargs)},
      {'fit_params': ['A', 'B', 'C', 'D', 'E'],
      'fit_jac': EQ101_fitting_jacobian,
       'initial_guesses': [
           {'A': -12.6, 'B': 2670.0, 'C': 0.0, 'D': 0.0, 'E': 0.0}, # perry dippr point benzamide
           {'A': -16.32, 'B': 3141.0, 'C': 0.0, 'D': 0.0, 'E': 0.0}, # perry dippr point 2-butanol
           {'A': -13.0, 'B': 2350.0, 'C': 0.0, 'D': 0.0, 'E': 0.0}, # perry dippr point 2-ethylhexanoic acid

           {'A': 0.263, 'B': 280.0, 'C': -1.7, 'D':0.0, 'E': 0.0}, # near dippr viscosity vinyl chloride
           {'A': -11.0, 'B': 1000.0, 'C': -1.7, 'D':0.0, 'E': 0.0}, # near dippr viscosity Methylisopropyl sulfide
           {'A': -12.0, 'B': 900.0, 'C': 0.2, 'D':0.0, 'E': 0.0}, # perry dippr point 107-02-8
           {'A': 1.55, 'B': 1400.0, 'C': -2.0, 'D': 0.0, 'E': 0.0}, # near dippr viscosity acetamide
           {'A': 7.5, 'B': 300.0, 'C': -2.8, 'D': 0.0, 'E': 0.0}, # near dippr viscosity benzene
           {'A': -9, 'B': 1210.0, 'C': -0.32, 'D': 0.0, 'E': 0.0}, # perry dippr point acetic acid
           
           {'A': 281.0, 'B': -32000.0, 'C': -38.8, 'D': 4e6, 'E': -2.002}, # near dippr viscosity cyclohexanol

           {'A': 59.7, 'B': -3520.0, 'C': -9.84, 'D': 9.03e12, 'E': -5.0}, # near dippr viscosity m-cresol
           {'A': -0.034, 'B': 390.0, 'C': -1.45, 'D': 5.0e12, 'E': -5.0}, # near dippr viscosity o-cresol
           {'A': -20.5, 'B': 2500.0, 'C': 1.2, 'D': 2.5e12, 'E': -5.0}, # near dippr viscosity ethylene glycol

           {'A': 180., 'B': -17000.0, 'C': -22.5, 'D':1e-17, 'E': -6.02}, # near dippr Psat 1-Undecanol
           {'A': -1.9, 'B': 388.0, 'C': -1.13, 'D': 1.5e14, 'E': -6.}, # near dippr mul 1,3-dichlorobenzene
           {'A': 7.88, 'B': -106.0, 'C': -2.7, 'D': 4.27e13, 'E': -6.}, # near dippr mul ethyltrichlorosilane
           
           {'A': 13.4, 'B': -233.0, 'C': -3.3, 'D': 1.75e20, 'E': -8.0}, # near dippr viscosity benzophenone
           {'A': -9.0, 'B': 1600.0, 'C': -2.15, 'D':3.3e22, 'E': -9.92}, # near dippr viscosity 1-Butanol
           {'A': 0.9, 'B': 1600.0, 'C': -2.15, 'D':3.4e22, 'E': -9.92}, # near dippr viscosity 1-Butanol point 2
           {'A': -9.65, 'B': 1200.0, 'C': -0.244, 'D': 9.05e34, 'E': -15.0}, # perry dippr point decane
           {'A': -7.8, 'B': 1200.0, 'C': -0.5, 'D': 4e23, 'E': -10.0}, # perry dippr point dodecane
           {'A': 40.0, 'B': -912.0, 'C': -7.56, 'D': 1.68e24, 'E': -10.0}, # perry dippr point formamide
           {'A': -6.3, 'B': 640.0, 'C': -0.7, 'D': 5.7e21, 'E': -10.0}, # perry dippr point hexane
                      
           {'A': -375.2, 'B': 17180.0, 'C': 66.67, 'D': -3.6368, 'E': 0.5}, # near dippr viscosity diethanolamine
           {'A': -158.9768, 'B': 13684.82, 'C': 19.79212, 'D': 1.78855e-05, 'E': 1.442815}, # near Diisopropanolamine chemsep liquid viscosity
           
           {'A': -804.55, 'B': 30490.0, 'C': 130.8, 'D':-0.155, 'E': 1.0}, # near dippr viscosity 1,2-propanediol
           {'A': -226.1, 'B': 6806.0, 'C': 37.55, 'D':-0.06085, 'E': 1.0}, # near dippr viscosity toluene
           {'A': -246.5, 'B': 3150.0, 'C': 50.0, 'D':-0.2255, 'E': 1.0}, # near dippr viscosity nitric oxide
           {'A': -395.0, 'B': 20000.0, 'C': 60.0, 'D':-5e-2, 'E': 1.0}, # near dippr viscosity 1,2-Butanediol
           {'A': -394.0, 'B': 19000.0, 'C': 60.0, 'D': -.05, 'E': 1.0}, # near dippr viscosity 1,2-butanediol
           {'A': -390.0, 'B': 18600.0, 'C': 60.0, 'D': -.055, 'E': 1.0}, # near dippr viscosity 1,3-butanediol
           {'A': 193.7, 'B': -8036, 'C': -29.5, 'D': 0.044, 'E': 1.0}, # near dippr Psat acetaldehyde
           {'A': 138.5, 'B': -7123.0, 'C': -19.64, 'D': 0.02645, 'E': 1.0}, # near dippr Psat acrolein
           {'A': -354.9911, 'B': 16471.68, 'C': 54.55389, 'D': -0.0481353, 'E': 1.0}, # near Triethylene glycol chemsep liquid viscosity
           {'A': 51.5, 'B': -1200.0, 'C': -6.4, 'D': 0.0285, 'E': 1.0}, # near dippr Psat oxygen
           {'A': 90.5, 'B': -4670.0, 'C': -11.6, 'D': 0.0172, 'E': 1.0}, # near dippr Psat ammonia
           {'A': 133.5, 'B': -7500.0, 'C': -18.4, 'D': 0.022, 'E': 1.0}, # near dippr Psat 1-hexyne
           {'A': 76.9, 'B': -7250.0, 'C': -8.25, 'D': 0.00616, 'E': 1.0}, # near dippr Psat hydrazine
           {'A': 150.0, 'B': -8900.0, 'C': -20.7, 'D': 0.022, 'E': 1.0}, # near dippr Psat pentanal
           {'A': 108.0, 'B': -6600.0, 'C': -14.2, 'D': 0.016, 'E': 1.0}, # near dippr Psat bromine
           {'A': 86.0, 'B': -4880.0, 'C': -10.9, 'D': 0.015, 'E': 1.0}, # near dippr Psat cyclobutane
           {'A': 93.1, 'B': -5500.0, 'C': -11.85, 'D': 0.014, 'E': 1.0}, # near dippr Psat 2-methyl-1-butene
           {'A': 211, 'B': -14000.0, 'C': -29.5, 'D': 0.0252, 'E': 1.0}, # near dippr Psat o-cresol
           {'A': 47, 'B': -5100.0, 'C': -3.67, 'D': 0.000516, 'E': 1.0}, # near dippr Psat 3-hexyne
           {'A': 463, 'B': -18300.0, 'C': -73.7, 'D': 0.093, 'E': 1.0}, # near dippr Psat diisopropylamine
           {'A': 21.65, 'B': -690.0, 'C': -0.39, 'D': 0.00475, 'E': 1.0}, # near dippr Psat something long
           {'A': 124, 'B': -7630.0, 'C': -16.45, 'D': 0.0165, 'E': 1.0}, # near dippr Psat 2-hexyne
           {'A': 136.6, 'B': -7200.0, 'C': -19.0, 'D': 0.0223, 'E': 1.0}, # near dippr Psat isopropylamine
           {'A': 337.6, 'B': -18500.0, 'C': -50.0, 'D': 0.0474, 'E': 1.0}, # near dippr Psat nonanal
           
           
           {'A': -20.449, 'B': -959.41, 'C': 4.2445, 'D': -9.5025e-05, 'E': 2.0}, # near Hydrogen iodide chemsep liquid viscosity
           {'A': -27.66295, 'B': 5326.5, 'C': 1.362383, 'D': -1.706454e-06, 'E': 2.0}, # near N-aminoethyl ethanolamine chemsep liquid viscosity
           {'A': -497.9054, 'B': 22666.52, 'C': 74.36022, 'D': -7.02789e-05, 'E': 2.0}, # near N-aminoethyl piperazine chemsep liquid viscosity
           {'A': 33.605, 'B': 4399.7, 'C': -8.9203, 'D': 2.1038e-05, 'E': 2.0}, # near Triethanolamine chemsep liquid viscosity
           {'A': -135.2818, 'B': 9167.078, 'C': 18.06409, 'D': -1.15446e-05, 'E': 2.0}, # near 1,4-butanediol chemsep liquid viscosity
           {'A': 20.959, 'B': -457.46, 'C': -4.9486, 'D': 6.5105e-06, 'E': 2.0}, # near Sulfur hexafluoride chemsep liquid viscosity
           {'A': -36.861, 'B': 2459.5, 'C': 3.4416, 'D': 7.0474e-06, 'E': 2.0}, # near Neopentane chemsep liquid viscosity
           {'A': -79.28, 'B': 4198.4, 'C': 10.393, 'D': -8.5568e-06, 'E': 2.0}, # near 1,4-dioxane chemsep liquid viscosity
           {'A': -98.08798, 'B': 4904.749, 'C': 13.57131, 'D': -2.19968e-05, 'E': 2.0}, # near 1-propanol chemsep liquid viscosity
           {'A': -9.949, 'B': 1214.4, 'C': -0.53562, 'D': 1.0346e-05, 'E': 2.0}, # near Methyl formate chemsep liquid viscosity
           {'A': -1098.989, 'B': 45628.63, 'C': 168.1502, 'D': -0.000185183, 'E': 2.0}, # near M-cresol chemsep liquid viscosity
           {'A': -10.876, 'B': 472.99, 'C': 0.14659, 'D': -1.3815e-05, 'E': 2.0}, # near Nitrous oxide chemsep liquid viscosity
           {'A': -107.9662, 'B': 6199.736, 'C': 14.5721, 'D': -1.7552e-05, 'E': 2.0}, # near 2-methyl-1-propanol chemsep liquid viscosity
           {'A': -0.287, 'B': 6081.0, 'C': -3.871, 'D': 1.52e-05, 'E': 2.0}, # near Diethanolamine chemsep liquid viscosity
           {'A': -702.8, 'B': 30403.5, 'C': 106.7, 'D': -0.0001164, 'E': 2.0}, # near Tetraethylene glycol chemsep liquid viscosity
           {'A': 19.33, 'B': 3027, 'C': -6.653, 'D': 3e-05, 'E': 2.0}, # near 2-butanol chemsep liquid viscosity
           {'A': 264.3, 'B': -7985.0, 'C': -44.1, 'D': 7.495e-05, 'E': 2.0}, # near Nitric acid chemsep liquid viscosity
           {'A': -260.7, 'B': 11505.0, 'C': 38.84, 'D': -6.16e-05, 'E': 2.0}, # near Sulfur trioxide chemsep liquid viscosity
           {'A': -161.558, 'B': 9388.5, 'C': 22.023, 'D': -1.219e-05, 'E': 2.0}, # near 2-pentanol chemsep liquid viscosity
           {'A': -58.53, 'B': 2991.0, 'C': 7.491, 'D': -1.103e-05, 'E': 2.0}, # near Acetic acid chemsep liquid viscosity
           {'A': -13.68, 'B': 5526.7, 'C': 15.76, 'D': -1.598e-05, 'E': 2.0}, # near Acrylic acid chemsep liquid viscosity
           {'A': 9.2895, 'B': -86.90, 'C': -3.7445, 'D':  5.848e-06, 'E': 2.0}, # near Fluorine chemsep liquid viscosity
           {'A': -7.0105, 'B': 766.6, 'C': -0.571, 'D': -1.617e-06, 'E': 2.0}, # near Diisopropylamine chemsep liquid viscosity
           {'A': -374.3, 'B': 18190.0, 'C': 55.1, 'D': -4.9166e-05, 'E': 2.0}, # near Diethylene glycol chemsep liquid viscosity
           {'A': -789.5, 'B': 22474.0, 'C': 129., 'D': -0.00032789, 'E': 2.0}, # near phosgene chemsep liquid viscosity
           {'A': -40.0, 'B': 1500.0, 'C': 4.8, 'D':-.000016, 'E': 2.0}, # near ammonia viscosity chemsep
           {'A': 62.9, 'B': -4137.0, 'C': -6.32, 'D': 9.2E-06, 'E': 2.0}, # near chemsep Psat ammonia
           {'A': 85.0, 'B': -7615.0, 'C': -9.31, 'D': 5.56E-06, 'E': 2.0}, # near dippr Psat m-xylene
           {'A': 73.7, 'B': -7260.0, 'C': -7.3, 'D': 4.16E-06, 'E': 2.0}, # near dippr Psat water
           {'A': 127.0, 'B': -12550.0, 'C': -15, 'D': 7.75E-06, 'E': 2.0}, # near dippr Psat phthalic anhydride
           {'A': 69.0, 'B': -5600.0, 'C': -7.1, 'D': 6.22E-06, 'E': 2.0}, # near dippr Psat acetone
           {'A': 66.0, 'B': -6015.0, 'C': -6.55, 'D': 4.32E-06, 'E': 2.0}, # near dippr Psat 1,2-dichloropropane
           {'A': 84.6, 'B': -5220.0, 'C': -9.9, 'D': 1.3E-05, 'E': 2.0}, # near dippr Psat 1,2-difluoroethane
           {'A': 302.0, 'B': -24320.0, 'C': -40.1, 'D': 1.75E-05, 'E': 2.0}, # near dippr Psat trinitrotoluene
           {'A': 113.0, 'B': -9750.0, 'C': -13.25, 'D': 7.13E-06, 'E': 2.0}, # near dippr Psat trinitrotoluene
           # {'A': 78.34, 'B': -8020.0, 'C': -8.15, 'D': 3.89E-06, 'E': 2.0}, # near dippr Psat 1,2,3-trimethylbenzene - uncomment to break things
           {'A': 137.0, 'B': -12000.0, 'C': -17, 'D': 8.1E-06, 'E': 2.0}, # near dippr Psat dodecane
           {'A': 136.0, 'B': -13500.0, 'C': -16., 'D': 5.61E-06, 'E': 2.0}, # near dippr Psat pentadecane
           {'A': 78.3, 'B': -6350.0, 'C': -8.5, 'D': 6.43E-06, 'E': 2.0}, # near dippr Psat 2,3-dimethylpentane
           {'A': 204.0, 'B': -19500.0, 'C': -25.5, 'D': 8.84E-06, 'E': 2.0}, # near dippr Psat eicosane
           {'A': 157.0, 'B': -15600.0, 'C': -19.0, 'D': 6.45E-06, 'E': 2.0}, # near dippr Psat heptadecane
           {'A': 30.0, 'B': -270.0, 'C': -2.6, 'D': 0.00053, 'E': 2.0}, # near dippr Psat neon
           {'A': 140.0, 'B': -13200.0, 'C': -16.9, 'D': 6.6e-06, 'E': 2.0}, # near dippr Psat tetradecane
           {'A': 173, 'B': -11600.0, 'C': -22.1, 'D': 1.37e-5, 'E': 2.0}, # near dippr Psat tert-butanol
           {'A': 506, 'B': -37500.0, 'C': -69.3, 'D': 2.74e-5, 'E': 2.0}, # near dippr Psat 1,3,5-trinitrobenzene
           {'A': 126.5, 'B': -12500.0, 'C': -15, 'D': 7.75e-6, 'E': 2.0}, # near dippr Psat
           {'A': 182.5, 'B': -17900.0, 'C': -22.5, 'D': 7.4e-6, 'E': 2.0}, # near dippr Psat nonadecane
           {'A': 212.5, 'B': -15400.0, 'C': -28.1, 'D': 2.16e-5, 'E': 2.0}, # near dippr Psat 1,2-propanediol
           {'A': 248.5, 'B': -32240.0, 'C': -30.0, 'D': 4.8e-06, 'E': 2.0}, # near dippr Psat terephthalic acid

           {'A': -75.8, 'B': 4175.0, 'C': 9.65, 'D': -7.3e-9, 'E': 3.0}, # near dippr mul hydrazine
           
           {'A': -116.3, 'B': 3834.0, 'C': 16.85, 'D': -2.59e-10, 'E': 4.0}, # near dippr mul hydrochloric acid
                      
           {'A': -14.0, 'B': 950.0, 'C': 0.5, 'D': -6.15e-17, 'E': 6.0}, # near dippr viscosity 1-chloropropane
           {'A': 84, 'B': -10500.0, 'C': -8.25, 'D': 1.65e-18, 'E': 6.0}, # near dippr Psat ethylene glycol
           {'A': 85.5, 'B': -11900.0, 'C': -8.33, 'D': 1.29e-18, 'E': 6.0}, # near dippr Psat benzamide
           {'A': 100.7, 'B': -11000.0, 'C': -10.7, 'D': 3.06e-18, 'E': 6.0}, # near dippr Psat benzyl alcohol
           {'A': 106.3, 'B': -9850.0, 'C': -11.7, 'D': 1.08e-18, 'E': 6.0}, # near dippr Psat 1-butanol
           {'A': 106.3, 'B': -13700.0, 'C': -11., 'D': 3.26e-18, 'E': 6.0}, # near dippr Psat diethanolamine
           {'A': 120.5, 'B': -13100.0, 'C': -13.5, 'D': 5.84e-18, 'E': 6.0}, # near dippr Psat heptanoic acid
           {'A': 140., 'B': -14800.0, 'C': -16, 'D': 6.42e-18, 'E': 6.0}, # near dippr Psat octanoic acid
           {'A': 163., 'B': -15200.0, 'C': -19.5, 'D': 1.07e-17, 'E': 6.0}, # near dippr Psat octanoic acid
           {'A': 73., 'B': -2750.0, 'C': -8.3, 'D': 9.7e-15, 'E': 6.0}, # near dippr Psat nitric oxide
           {'A': 129., 'B': -17000.0, 'C': -14.0, 'D': 2.156e-18, 'E': 6.0}, # near dippr Psat succinic acid
           
           {'A': -17.7, 'B': 850.0, 'C': 1.05, 'D': -1.2e-18, 'E': 7.0}, # near dippr viscosity 1-difluoromethane

           {'A': -7.2, 'B': 535.0, 'C': -0.575, 'D':-4.66e-27, 'E': 10.0}, # near dippr viscosity butane
           {'A': -53.0, 'B': 3700.0, 'C': -5.8, 'D':-6e-29, 'E': 10.0}, # near dippr viscosity water
           {'A': -8.9, 'B': 205.0, 'C': -0.38, 'D': -1.3e-22, 'E': 10}, # perry dippr point argon
           {'A': -9.63, 'B': -3.84, 'C': -1.46, 'D': -1.07e-8, 'E': 10}, # perry dippr point helium
           {'A': -11.7, 'B': 25.0, 'C': -0.26, 'D': -4e-16, 'E': 10}, # perry dippr mul point hydrogen
           {'A': -20.0, 'B': 285.0, 'C': -1.8, 'D': -6.2e-22, 'E': 10}, # perry dippr point 132259-10-0
           {'A': -25.1, 'B': 1380.0, 'C': 2.1, 'D': 4.5e-27, 'E': 10.0}, # perry dippr point chloromethane
           # {'A': -25.132, 'B': 1381.9, 'C': 2.0811, 'D': -4.4999e-27, 'E': 10.0}, # perry dippr point chloromethane exact for testing
            ]
           }
      ),
     'DIPPR102': (['A', 'B', 'C', 'D'],
      [],
      {'f': EQ102,
       'f_der': lambda T, **kwargs: EQ102(T, order=1, **kwargs),
       'f_int': lambda T, **kwargs: EQ102(T, order=-1, **kwargs),
       'f_int_over_T': lambda T, **kwargs: EQ102(T, order=-1j, **kwargs)},
     {'fit_params': ['A', 'B', 'C', 'D'],
      'fit_jac': EQ102_fitting_jacobian,
      'initial_guesses': [
           {'A': 0.00123, 'B': 1.25, 'C': 60900.0, 'D': -1968000.0},# chemsep
           {'A': -238., 'B': 1.05, 'C': -4970000000.0, 'D': -89500000000.0}, # chemsep
           {'A': 1.2e-7, 'B': 0.8, 'C': 77.0, 'D': 0.0}, # near dippr mug Acetaldehyde
           {'A': 1.4e-7, 'B': 0.75, 'C': 277.0, 'D': 0.0}, # near dippr mug Acetamide
           {'A': 2.7e-8, 'B': 1.0, 'C': 7.5, 'D': 0.0}, # near dippr mug Acetic acid
           {'A': 3.1e-8, 'B': 0.96, 'C': 0.0, 'D': 0.0}, # near dippr mug sec-Butyl mercaptan
           {'A': 2e-6, 'B': 0.42, 'C': 900.0, 'D': -4e4}, # near dippr mug Butyric acid
           {'A': 3.5e-6, 'B': 0.37, 'C': 1200.0, 'D': 0.0}, # near dippr mug N,N-Dimethyl formamide
           {'A': 3.5e-7, 'B': 1.8, 'C': 0.0, 'D': 0.0}, # near dippr kg Acetaldehyde
           {'A': 4e-4, 'B': 0.8, 'C': 440.0, 'D': 1.4e5}, # near dippr kg Acetic anhydride
           {'A': 3e-4, 'B': 0.78, 'C': -.7, 'D': 2.1e3}, # near dippr kg air
           {'A': 2.85e-4, 'B': 1.0, 'C': -200.0, 'D': 2.2e4}, # near dippr kg Deuterium
           {'A': -6.5e5, 'B': 0.286, 'C': -1.7e10, 'D': -1.74e13}, # near dippr kg Furan
           {'A': 1.6e-5, 'B': 1.3, 'C': 75.0, 'D': -8000.0}, # near chemsep kg ammonia
           {'A': 0.051, 'B': 0.45, 'C': 5450.0, 'D': 2e6}, # near dippr kg butane
           {'A': 0.011, 'B': 0.716, 'C': 175.0, 'D': 346000.0}, # near dippr kg cyclopentene
           {'A': 2.24e-5, 'B': 1.2, 'C': -147.0, 'D': 132000.0}, # near dippr kg 2,3-dimethylpentane
           {'A': 3.8e-5, 'B': 1.05, 'C': 287.0, 'D': 0.0}, # near dippr kg bromomethane
           {'A': 3e-6, 'B': 1.41, 'C': 0.0, 'D': 0.0}, # near dippr kg ethyltrichlorosilane
           {'A': 0.0009, 'B': 0.774, 'C': 460.0, 'D': 230600.0}, # near dippr kg ethyltrichlorosilane
           {'A': -4940000.0, 'B': -0.165, 'C': 1.56e9, 'D': -1.58e13}, # near dippr kg  1-hexanol
           {'A': 4.65e-6, 'B': 1.37, 'C': -211.0, 'D': 58300.0}, # near dippr kg  hydrogen cyanide
           {'A': -0.01, 'B': 0.65, 'C': -7330.0, 'D': -2.68e5}, # near dippr kg ethanol
           {'A': 44.8, 'B': -0.71, 'C': -3500.0, 'D': 5.35e6}, # near dippr kg formaldehyde
           {'A': -1.1, 'B': 0.11, 'C': -9830.0, 'D': -7.54e6}, # near dippr kg propane
           {'A': 3.46e-5, 'B': 1.12, 'C': 18.7, 'D': 0.0}, # near dippr kg hydrofluoric acid
           {'A': -8150000.0, 'B': -0.305, 'C': 1.89e9, 'D': -11.8e12}, # near dippr kg ethylene glycol
           {'A': 2.1e-5, 'B': 1.29, 'C': 488.0, 'D': 0.0}, # near dippr kg 1-heptene
           {'A': 4.5e-5, 'B': 1.2, 'C': 420.0, 'D': 0.0}, # near dippr kg propene
           {'A': 1.7e-6, 'B': 1.67, 'C': 660.0, 'D': -95400.0}, # near dippr kg acetic acid
           {'A': 0.0, 'B': 4000.0, 'C': 0.75, 'D': 0.0}, #
           {'A': 1e9, 'B': -5.0, 'C': -1500, 'D': 1e6}, #
           {'A': 0.0, 'B': 3600.0, 'C': 0.73, 'D': 0.0}, #
           {'A': 0.0076, 'B': 0.51, 'C': 2175, 'D': 185000.0}, #
        ]}),
     'DIPPR104': (['A', 'B'],
      ['C', 'D', 'E'],
      {'f': EQ104,
       'f_der': lambda T, **kwargs: EQ104(T, order=1, **kwargs),
       'f_int': lambda T, **kwargs: EQ104(T, order=-1, **kwargs),
       'f_int_over_T': lambda T, **kwargs: EQ104(T, order=-1j, **kwargs)},
      
      
     {'fit_params': ['A', 'B', 'C', 'D', 'E'], 'initial_guesses': [
         {'A': 0.4, 'B': -700.0, 'C': -2e8, 'D': -3e21, 'E': 4e23},
         {'A': 0.02, 'B': -3.0, 'C': -400.0, 'D': 5e8, 'E': -5e9},
         ]}),
     
     
     
     'DIPPR105': (['A', 'B', 'C', 'D'],
      [],
      {'f': EQ105,
       'f_der': lambda T, **kwargs: EQ105(T, order=1, **kwargs),
       'f_der2': lambda T, **kwargs: EQ105(T, order=2, **kwargs),
       'f_der3': lambda T, **kwargs: EQ105(T, order=3, **kwargs)},
      {'fit_params': ['A', 'B', 'C', 'D'],'fit_jac': EQ105_fitting_jacobian,
       'initial_guesses': [
          {'A': 500.0, 'B': 0.25, 'C': 630.0, 'D': 0.22,}, # near 2-Octanol dippr volume
          {'A': 1370.0, 'B': 0.238, 'C': 588.0, 'D': 0.296,}, # near Nitromethane dippr volume
          {'A': 976.0, 'B': 0.282, 'C': 483.0, 'D': 0.22529,}, # near Methyldichlorosilane dippr volume
          {'A': 7247.0, 'B': 0.418, 'C': 5.2, 'D': 0.24,}, # near helium dippr volume
          {'A': 4289.0, 'B': 0.285, 'C': 144.0, 'D': 0.29}, # near Fluorine dippr volume
          {'A': 4.05E3, 'B': 0.27, 'C': 400.,'D': 0.313},  # near ammonia dippr volume
          {'A': 2770.0, 'B': 0.26, 'C': 305.,'D': 0.291},  # near carbon dioxide dippr volume
          {'A': 1375.0, 'B': 0.275, 'C': 270.,'D': 0.293},  # near propane dippr volume
          {'A': 5410.0, 'B': 0.35, 'C': 33.,'D': 0.27},  # near hydrogen dippr volume
          {'A': 2900.0, 'B': 0.275, 'C': 133.,'D': 0.28},  # near carbon monoxide dippr volume
          {'A': 427.0, 'B': 0.18, 'C': 1110.,'D': 0.285},  # near terephthalic acid dippr volume
          {'A': 1100.0, 'B': 0.28, 'C': 620.,'D': 0.31},  # near dimethyl disulfide dippr volume
          {'A': 1170.0, 'B': 0.23, 'C': 450.,'D': 0.285},  # near 1,2-difluoroethane dippr volume
          {'A': 2450.0, 'B': 0.275, 'C': 310.,'D': 0.29},  # near ethyne dippr volume
          {'A': 1450.0, 'B': 0.268, 'C': 365.,'D': 0.29},  # near propene dippr volume
          {'A': 1940.0, 'B': 0.24, 'C': 590.,'D': 0.244},  # near formic acid dippr volume
          
          {'A': 1.05, 'B': 0.258, 'C': 540.,'D': 0.268},  # near some chemsep liquid densities
          {'A': 2.15, 'B': 0.27, 'C': 415.,'D': 0.286},  # near some chemsep liquid densities
          {'A': 0.048, 'B': 0.09, 'C': 587.,'D': 0.133},  # near some chemsep liquid densities
          {'A': 0.68, 'B': 0.26, 'C': 500.,'D': 0.259},  # near some chemsep liquid densities
          {'A': 1.105, 'B': 0.245, 'C': 508.,'D': 0.274},  # near some chemsep liquid densities
          {'A': 0.9966, 'B': 0.343, 'C': 803.,'D': 0.5065},  # near some chemsep liquid densities
          {'A': 1.32, 'B': 0.27, 'C': 370.,'D': 0.2785},  # near some chemsep liquid densities
          {'A': 0.9963, 'B': 0.3426, 'C': 803.,'D': 0.5065},  # near some chemsep liquid densities
          {'A': 1.002, 'B': 0.2646, 'C': 425.2,'D': 0.2714},  # near some chemsep liquid densities
          {'A': 0.6793, 'B': 0.2165, 'C': 433.3,'D': 0.20925},  # near some chemsep liquid densities
          {'A': 0.01382, 'B': 0.07088, 'C': 810.0,'D': 0.13886},  # near some chemsep liquid densities
          {'A': 0.99663, 'B': 0.34261, 'C': 803.06,'D': 0.50647},  # near some chemsep liquid densities
          {'A': 0.4708, 'B': 0.22934, 'C': 664.5,'D': 0.22913},  # near some chemsep liquid densities
          {'A': 0.27031, 'B': 0.13967, 'C': 595.0,'D': 0.17588},  # near some chemsep liquid densities
          {'A': 0.99773, 'B': 0.19368, 'C': 469.15,'D': 0.19965},  # near some chemsep liquid densities
          {'A': 0.4436, 'B': 0.23818, 'C': 568.77,'D': 0.25171},  # near some chemsep liquid densities
          {'A': 0.8193, 'B': 0.25958, 'C': 561.1,'D': 0.28941},  # near some chemsep liquid densities
          {'A': 1.3663, 'B': 0.25297, 'C': 456.4,'D': 0.27948},  # near some chemsep liquid densities
          {'A': 0.42296, 'B': 0.21673, 'C': 611.55,'D': 0.2517},  # near some chemsep liquid densities
          {'A': 0.50221, 'B': 0.23722, 'C': 631.11,'D': 0.26133},  # near some chemsep liquid densities
          {'A': 0.67524, 'B': 0.24431, 'C': 645.61,'D': 0.26239},  # near some chemsep liquid densities
          {'A': 0.5251, 'B': 0.20924, 'C': 736.61,'D': 0.18363},  # near some chemsep liquid densities
          
          {'A': 0.13, 'B': 0.23, 'C': 910.,'D': 0.29},  # 
          {'A': 9.0, 'B': 0.5, 'C': 2400.,'D': 0.58},  # 
          {'A': 1.0, 'B': 0.14, 'C': 1000.0,'D': 0.1},  # 
          {'A': 0.24, 'B': 0.05, 'C': 6000.0,'D': 0.2},  # 
          {'A': 6.5, 'B': 0.5, 'C': 3.5, 'D': 0.2},  # 
          {'A': 15.0, 'B': 0.3, 'C': 7000.0, 'D': 0.3},  # 
          {'A': 0.1, 'B': 0.05, 'C': 3300.0, 'D': 0.1},  # 
          ]}),

     'DIPPR106': (['Tc', 'A', 'B'],
      ['C', 'D', 'E'],
      {'f': EQ106,
       'f_der': lambda T, **kwargs: EQ106(T, order=1, **kwargs),
       'f_der2': lambda T, **kwargs: EQ106(T, order=2, **kwargs),
       'f_der3': lambda T, **kwargs: EQ106(T, order=3, **kwargs)},
     {'fit_params': ['A', 'B', 'C', 'D', 'E'], 'fit_jac': EQ106_fitting_jacobian,
      'initial_guesses': [
          {'A': 47700.0, 'B': 0.37, 'C': 0.,'D': 0.0, 'E': 0.0},  # near vinyl acetate dippr Hvap
          {'A': 23200.0, 'B': 0.36, 'C': 0.,'D': 0.0, 'E': 0.0},  # near ethyne dippr Hvap
          {'A': 8730.0, 'B': 0.35, 'C': 0.,'D': 0.0, 'E': 0.0},  # near argon dippr Hvap
          {'A': 125.0, 'B': 1.3, 'C': -2.7,'D': 1.7, 'E': 0.0},  # near helium dippr Hvap
          {'A': 1010.0, 'B': 0.7, 'C': -1.8,'D': 1.45, 'E': 0.0},  # near hydrogen dippr Hvap
          {'A': 135000.0, 'B': 13.5, 'C': -23.5,'D': 10.8, 'E': 0.0},  # near hydrofluoric acid dippr Hvap
          
          {'A': 7385650.0, 'B': 0.27668, 'C': 0.21125, 'D': -0.8368, 'E': 0.723}, # near chemsep Hvap air
          {'A': 62115220.0, 'B': 1.00042, 'C': -0.589, 'D': -0.2779, 'E': 0.31358,}, # near chemsep Hvap 2,2-dimethylhexane
          {'A': 4761730.0, 'B': -11.56, 'C': 30.7, 'D': -31.89, 'E': 12.678}, # near chemsep Hvap Dimethylacetylene
          # {'A': 0.119, 'B': 1.59, 'C': -0.25, 'D': 0.0, 'E': 0.0},
          # {'A': 35e6, 'B': 0.1, 'C': 0.0325, 'D': 0.25, 'E': 0.0},
           ]
                  
      }),
     'YawsSigma': (['Tc', 'A', 'B'],
      ['C', 'D', 'E'],
      {'f': EQ106,
       'f_der': lambda T, **kwargs: EQ106(T, order=1, **kwargs),
       'f_der2': lambda T, **kwargs: EQ106(T, order=2, **kwargs),
       'f_der3': lambda T, **kwargs: EQ106(T, order=3, **kwargs)},
      {'fit_params': ['A', 'B']}),

     'DIPPR107': ([],
      ['A', 'B', 'C', 'D', 'E'],
      {'f': EQ107,
       'f_der': lambda T, **kwargs: EQ107(T, order=1, **kwargs),
       'f_int': lambda T, **kwargs: EQ107(T, order=-1, **kwargs),
       'f_int_over_T': lambda T, **kwargs: EQ107(T, order=-1j, **kwargs)},
      {'fit_params': ['A', 'B', 'C', 'D', 'E'],
       'fit_jac': EQ107_fitting_jacobian,
       'initial_guesses':[
          {'A': 325000.0, 'B': 110000.0, 'C': 1640.0, 'D': 745000.0, 'E': 726.},
          {'A': 50000.0, 'B': 5e4, 'C': 300.0, 'D': 40000.0, 'E': 200.},
          {'A': 60000.0, 'B': 90000.0, 'C': 800.0, 'D': 63000.0, 'E': -2000.},
          {'A': 30000.0, 'B': 10000.0, 'C': 1000.0, 'D': 10000.0, 'E': 400.},
          {'A': 90000.0, 'B': 225000.0, 'C': 600.0, 'D': 200000.0, 'E': 2000.},
          {'A': 20000.0, 'B': 3000.0, 'C': 3000.0, 'D': 20000.0, 'E': 100.},
          {'A': 100000.0, 'B': 300000.0, 'C': 800.0, 'D': -125000, 'E': 1000.},
          {'A': 350000.0, 'B': 150000.0, 'C': 3000.0, 'D': -500000, 'E': 300.},
          {'A': 150000.0, 'B': 1e6, 'C': 500.0, 'D': -800000, 'E': 650.},
          {'A': 350000.0, 'B': 1e6, 'C': 2250.0, 'D': 800000, 'E': 1000.},
          {'A': 40000.0, 'B': 2500, 'C': 1000.0, 'D': 5000, 'E': 7500.},
          {'A': 45000.0, 'B': 60000, 'C': 500.0, 'D': 6000, 'E': 4000.},
          {'A': 750000.0, 'B': 1.5e6, 'C': 750.0, 'D': 600000, 'E': 2500.},
          {'A': 50000.0, 'B': 200000, 'C': 1200.0, 'D': 100000, 'E': 500.},
          {'A': 820000.0, 'B': 375000, 'C': 1750.0, 'D': -1e6, 'E': 275.},
          {'A': 150000.0, 'B': 145000, 'C': 1225.0, 'D': -5.75e7, 'E': 7.75},
        ]}),
      # 
     'DIPPR114': (['Tc', 'A', 'B', 'C', 'D'],
      [],
      {'f': EQ114,
       'f_der': lambda T, **kwargs: EQ114(T, order=1, **kwargs),
       'f_int': lambda T, **kwargs: EQ114(T, order=-1, **kwargs),
       'f_int_over_T': lambda T, **kwargs: EQ114(T, order=-1j, **kwargs)},
     {'fit_params': ['A', 'B', 'C', 'D'], 'initial_guesses': [
          {'A': 65.0, 'B': 30000, 'C': -850, 'D': 2000.0},
          {'A': 150.0, 'B': -45000, 'C': -2500, 'D': 6000.0},
         ]}),
     
     
     'DIPPR115': (['A', 'B'],
      ['C', 'D', 'E'],
      {'f': EQ115,
       'f_der': lambda T, **kwargs: EQ115(T, order=1, **kwargs),
       'f_der2': lambda T, **kwargs: EQ115(T, order=2, **kwargs),
       'f_der3': lambda T, **kwargs: EQ115(T, order=3, **kwargs)},
      {'fit_params': ['A', 'B', 'C', 'D', 'E'],
       'initial_guesses': [
           {'A': 38.0, 'B': -9100, 'C': 0.16, 'D': -8.3e-7, 'E': 0.0},
           ]}),
     'DIPPR116': (['Tc', 'A', 'B', 'C', 'D', 'E'],
      [],
      {'f': EQ116,
       'f_der': lambda T, **kwargs: EQ116(T, order=1, **kwargs),
       'f_int': lambda T, **kwargs: EQ116(T, order=-1, **kwargs),
       'f_int_over_T': lambda T, **kwargs: EQ116(T, order=-1j, **kwargs)},
      {'fit_params': ['A', 'B', 'C', 'D', 'E']}),
     'DIPPR127': (['A', 'B', 'C', 'D', 'E', 'F', 'G'],
      [],
      {'f': EQ127,
       'f_der': lambda T, **kwargs: EQ127(T, order=1, **kwargs),
       'f_int': lambda T, **kwargs: EQ127(T, order=-1, **kwargs),
       'f_int_over_T': lambda T, **kwargs: EQ127(T, order=-1j, **kwargs)},
      {'fit_params': ['A', 'B', 'C', 'D', 'E', 'F', 'G'], 'initial_guesses': [
          {'A': 35000.0, 'B': 1e8, 'C': -3e3, 'D': 5e5, 'E': -500.0, 'F': 7.5e7, 'G': -2500.0},
          {'A': 35000.0, 'B': 1e5, 'C': -7.5e3, 'D': 2e5, 'E': -800.0, 'F': 2e5, 'G': -2500.0},
          {'A': 0.0, 'B': 33000.0, 'C': 1.9e5, 'D': 2e3, 'E': 1e5, 'F': 4900.0, 'G': 1.6e5},
          {'A': 33000.0, 'B': 1e4, 'C': -2.5e3, 'D': 16000, 'E': -600.0, 'F': 7000, 'G': -12500.0},
          {'A': 33000.0, 'B': 3.5e7, 'C': -6500.0, 'D': -3.5e7, 'E': 6500.0, 'F': 50000.0, 'G': -1500.0},
          {'A': 33000.0, 'B': 2.5e4, 'C': -250.0, 'D': 150000.0, 'E': 1300.0, 'F': 1e5, 'G': 3200.0},
          ]}),

        # Alpha functions
        'Twu91_alpha_pure': (['Tc', 'c0', 'c1', 'c2'], [], {'f': Twu91_alpha_pure}, {'fit_params': ['c0', 'c1', 'c2'], 
                             'initial_guesses': []}),
        
        'Heyen_alpha_pure': (['Tc', 'c1', 'c2'], [], {'f': Heyen_alpha_pure}, {'fit_params': ['c1', 'c2'], 
                             'initial_guesses': []}),
        
        'Harmens_Knapp_alpha_pure': (['Tc', 'c1', 'c2'], [], {'f': Harmens_Knapp_alpha_pure}, {'fit_params': ['c1', 'c2'], 
                             'initial_guesses': []}),
        
        'Mathias_Copeman_untruncated_alpha_pure': (['Tc', 'c1', 'c2', 'c3'], [], {'f': Mathias_Copeman_untruncated_alpha_pure}, {'fit_params': ['c1', 'c2', 'c3'],
                             'initial_guesses': []}),

        'Mathias_1983_alpha_pure': (['Tc', 'c1', 'c2'], [], {'f': Mathias_1983_alpha_pure}, {'fit_params': ['c1', 'c2'], 
                             'initial_guesses': []}),
        
        'Soave_1972_alpha_pure': (['Tc', 'c0',], [], {'f': Soave_1972_alpha_pure}, {'fit_params': ['c0',], 
                             'initial_guesses': []}),
        
        'Soave_1979_alpha_pure': (['Tc', 'M', 'N'], [], {'f': Soave_1979_alpha_pure}, {'fit_params': ['M', 'N'], 
                             'initial_guesses': []}),
        
        'Gibbons_Laughton_alpha_pure': (['Tc', 'c1', 'c2'], [], {'f': Gibbons_Laughton_alpha_pure}, {'fit_params': ['c1', 'c2'], 
                             'initial_guesses': []}),
        
        'Soave_1984_alpha_pure': (['Tc', 'c1', 'c2'], [], {'f': Soave_1984_alpha_pure}, {'fit_params': ['c1', 'c2'], 
                             'initial_guesses': []}),
        
        'Yu_Lu_alpha_pure': (['Tc', 'c1', 'c2', 'c3', 'c4'], [], {'f': Yu_Lu_alpha_pure}, {'fit_params': ['c1', 'c2', 'c3', 'c4'], 
                             'initial_guesses': [{'c1': .4, 'c2': 0.536843, 'c3': -0.39244, 'c4': 0.26507},
                                                 {'c1': 1.1, 'c2': 0.536843, 'c3': -0.39244, 'c4': 0.26507},
                                                 {'c1': .6, 'c2': 0.536843, 'c3': -0.39244, 'c4': 0.26507},
                                                 ]}),
        
        'Trebble_Bishnoi_alpha_pure': (['Tc', 'c1',], [], {'f': Trebble_Bishnoi_alpha_pure}, {'fit_params': ['c1',], 
                             'initial_guesses': []}),
        
        'Melhem_alpha_pure': (['Tc', 'c1', 'c2'], [], {'f': Melhem_alpha_pure}, {'fit_params': ['c1', 'c2'], 
                             'initial_guesses': []}),

        'Androulakis_alpha_pure': (['Tc', 'c1', 'c2', 'c3'], [], {'f': Androulakis_alpha_pure}, {'fit_params': ['c1', 'c2', 'c3'],
                             'initial_guesses': []}),
        'Schwartzentruber_alpha_pure': (['Tc', 'c1', 'c2', 'c3', 'c4'], [], {'f': Schwartzentruber_alpha_pure},
                                        {'fit_params': ['c1', 'c2', 'c3', 'c4'],
                             'initial_guesses': []}),

        'Almeida_alpha_pure': (['Tc', 'c1', 'c2', 'c3'], [], {'f': Almeida_alpha_pure}, {'fit_params': ['c1', 'c2', 'c3'],
                             'initial_guesses': []}),

        'Soave_1993_alpha_pure': (['Tc', 'c1', 'c2'], [], {'f': Soave_1993_alpha_pure}, {'fit_params': ['c1', 'c2'], 
                             'initial_guesses': []}),
        
        'Gasem_alpha_pure': (['Tc', 'c1', 'c2', 'c3'], [], {'f': Gasem_alpha_pure}, {'fit_params': ['c1', 'c2', 'c3'],
                             'initial_guesses': []}),
        
        'Coquelet_alpha_pure': (['Tc', 'c1', 'c2', 'c3'], [], {'f': Coquelet_alpha_pure}, {'fit_params': ['c1', 'c2', 'c3'],
                             'initial_guesses': []}),
        
        'Haghtalab_alpha_pure': (['Tc', 'c1', 'c2', 'c3'], [], {'f': Haghtalab_alpha_pure}, {'fit_params': ['c1', 'c2', 'c3'],
                             'initial_guesses': []}),
        
        'Saffari_alpha_pure': (['Tc', 'c1', 'c2', 'c3'], [], {'f': Saffari_alpha_pure}, {'fit_params': ['c1', 'c2', 'c3'],
                             'initial_guesses': []}),
        
        'Chen_Yang_alpha_pure': (['Tc', 'omega', 'c1', 'c2', 'c3', 'c4', 'c5', 'c6', 'c7'], [], {'f': Chen_Yang_alpha_pure}, {'fit_params': ['c1', 'c2', 'c3', 'c4', 'c5', 'c6', 'c7'], 
                             'initial_guesses': [
                                 
                                                 ]}),

    }

    # Aliases from the DDBST
    correlation_models['Wagner2,5'] = correlation_models['Wagner']
    correlation_models['Wagner3,6'] = correlation_models['Wagner_original']
    correlation_models['Andrade'] = correlation_models['Viswanath_Natarajan_2']
    
    
    # Don't know why TDE has  Hvap = exp(A)*{1 - ( T / Tc )}^n
    # In other places they have it right: https://trc.nist.gov/TDE/TDE_Help/Eqns-Pure-Hvap/Yaws.VaporizationH.htm
    correlation_models['YawsHvap'] = correlation_models['YawsSigma']


    available_correlations = frozenset(correlation_models.keys())

    correlation_parameters = {k: k + '_parameters' for k in correlation_models.keys()}



    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        # By default, share state among subsequent objects
        return self

    def __eq__(self, other):
        return self.__hash__() == hash(other)

    hash_ignore_props = ('extrapolation_coeffs', 'prop_cached',
                         'TP_cached', 'tabular_data_interpolators',
                         'tabular_data_interpolators_P', 'T_cached')
    def __hash__(self):
        d = self.__dict__
        # extrapolation values and interpolation objects should be ignored
        temp_store = {}
        for k in self.hash_ignore_props:
            try:
                temp_store[k] = d[k]
                del d[k]
            except:
                pass
        ans = hash_any_primitive((self.__class__, d))
        d.update(temp_store)

        return ans

    def __repr__(self):
        r'''Create and return a string representation of the object. The design
        of the return string is such that it can be :obj:`eval`'d into itself.
        This is very convinient for creating tests. Note that several methods
        are not compatible with the :obj:`eval`'ing principle.

        Returns
        -------
        repr : str
            String representation, [-]
        '''
        clsname = self.__class__.__name__
        base = '%s(' % (clsname)
        if self.CASRN:
            base += 'CASRN="%s", ' %(self.CASRN)
        for k in self.custom_args:
            v = getattr(self, k)
            if v is not None:
                base += '%s=%s, ' %(k, v)

        extrap_str = '"%s"' %(self.extrapolation) if self.extrapolation is not None else 'None'
        base += 'extrapolation=%s, ' %(extrap_str)

        method_str = '"%s"' %(self.method) if self.method is not None else 'None'
        base += 'method=%s, ' %(method_str)
        if self.tabular_data:
            if not (len(self.tabular_data) == 1 and VDI_TABULAR in self.tabular_data):
                base += 'tabular_data=%s, ' %(self.tabular_data)

        if self.P_dependent:
            method_P_str = '"%s"' %(self.method_P) if self.method_P is not None else 'None'
            base += 'method_P=%s, ' %(method_P_str)
            if self.tabular_data_P:
                base += 'tabular_data_P=%s, ' %(self.tabular_data_P)
            if 'tabular_extrapolation_permitted' in self.__dict__:
                base += 'tabular_extrapolation_permitted=%s, ' %(self.tabular_extrapolation_permitted)


        if hasattr(self, 'poly_fit_Tmin') and self.poly_fit_Tmin is not None:
            base += 'poly_fit=(%s, %s, %s), ' %(self.poly_fit_Tmin, self.poly_fit_Tmax, self.poly_fit_coeffs)
        for k in self.correlation_parameters.values():
            extra_model = getattr(self, k, None)
            if extra_model:
                base += '%s=%s, ' %(k, extra_model)


        if base[-2:] == ', ':
            base = base[:-2]
        return base + ')'

    def __call__(self, T):
        r'''Convenience method to calculate the property; calls
        :obj:`T_dependent_property <thermo.utils.TDependentProperty.T_dependent_property>`. Caches previously calculated value,
        which is an overhead when calculating many different values of
        a property. See :obj:`T_dependent_property <thermo.utils.TDependentProperty.T_dependent_property>` for more details as to the
        calculation procedure.

        Parameters
        ----------
        T : float
            Temperature at which to calculate the property, [K]

        Returns
        -------
        prop : float
            Calculated property, [`units`]
        '''
        if T == self.T_cached:
            return self.prop_cached
        else:
            self.prop_cached = self.T_dependent_property(T)
            self.T_cached = T
            return self.prop_cached

    def as_json(self, references=1):
        r'''Method to create a JSON serialization of the property model
        which can be stored, and reloaded later.

        Parameters
        ----------
        references : int
            How to handle references to other objects; internal parameter, [-]

        Returns
        -------
        json_repr : dict
            JSON-friendly representation, [-]

        Notes
        -----

        Examples
        --------
        '''
        # vaguely jsonpickle compatible
        d = self.__dict__.copy()
        d["py/object"] = self.__full_path__
#        print(self.__full_path__)
        d["json_version"] = 1

        d['all_methods'] = list(d['all_methods'])
        d['tabular_data_interpolators'] = {}

        ignored = ('correlations', 'extrapolation_coeffs')
        for i in ignored:
            try: del d[i]
            except: pass

        if hasattr(self, 'all_methods_P'):
            d['all_methods_P'] = list(d['all_methods_P'])
            d['tabular_data_interpolators_P'] = {}

        del_objs = references == 0
        for name in self.pure_references:
            prop_obj = getattr(self, name)
            if prop_obj is not None and type(prop_obj) not in (float, int):
                if del_objs:
                    del d[name]
                else:
                    d[name] = prop_obj.as_json()

        for name in self._json_obj_by_CAS:
            CASRN = self.CASRN
            if hasattr(self, name):
                d[name] = CASRN
        try:
            eos = getattr(self, 'eos')
            if eos:
                d['eos'] = eos[0].as_json()
        except:
            pass
        return d

    @classmethod
    def _load_json_CAS_references(cls, d):
        try:
            d['CP_f'] = coolprop_fluids[d['CP_f']]
        except:
            pass

    @classmethod
    def from_json(cls, json_repr):
        r'''Method to create a property model from a JSON
        serialization of another property model.

        Parameters
        ----------
        json_repr : dict
            JSON-friendly representation, [-]

        Returns
        -------
        model : :obj:`TDependentProperty` or :obj:`TPDependentProperty`
            Newly created object from the json serialization, [-]

        Notes
        -----
        It is important that the input string be in the same format as that
        created by :obj:`TDependentProperty.as_json`.

        Examples
        --------
        '''
        d = json_repr#serialize.json.loads(json_repr)
        cls._load_json_CAS_references(d)
        try:
            eos = d['eos']
            if eos is not None:
                d['eos'] = [GCEOS.from_json(eos)]
        except:
            pass

        d['all_methods'] = set(d['all_methods'])
        try:
            d['all_methods_P'] = set(d['all_methods_P'])
        except:
            pass
        d['T_limits'] = {k: tuple(v) for k, v in d['T_limits'].items()}
        d['tabular_data'] = {k: tuple(v) for k, v in d['tabular_data'].items()}

        for k, sub_cls in zip(cls.pure_references, cls.pure_reference_types):
            if k in d:
                if type(d[k]) is dict:
                    sub_json = d[k]
                    d[k] = sub_cls.from_json(sub_json)
                    
                    

        d['correlations'] = correlations = {}
        for correlation_name in cls.correlation_models.keys():
            # Should be lazy created?
            correlation_key = cls.correlation_parameters[correlation_name]
            if correlation_key in d:
                call = cls.correlation_models[correlation_name][2]['f']
                for model_name, kwargs in d[correlation_key].items():
                    model_kwargs = kwargs.copy()
                    model_kwargs.pop('Tmin')
                    model_kwargs.pop('Tmax')
                    correlations[model_name] = (call, model_kwargs, correlation_name)

        d['extrapolation_coeffs'] = {}
        del d['py/object']
        del d["json_version"]
        new = cls.__new__(cls)
        new.__dict__ = d
        return new

    @classmethod
    def _fit_export_polynomials(cls, method=None, start_n=3, max_n=30,
                                eval_pts=100, save=False):
        import json
        dat = {}
        folder = os.path.join(source_path, cls.name)

        sources = cls._method_indexes()

        fit_max_n = cls._fit_max_n

        if method is None:
            methods = list(sources.keys())
            indexes = list(sources.values())
        else:
            methods = [method]
            indexes = [sources[method]]
        for method, index in zip(methods, indexes):
            method_dat = {}
            n = cls._fit_force_n.get(method, None)
            max_n_method = fit_max_n[method] if method in fit_max_n else max_n
            for CAS in index:
                print(CAS)
                obj = cls(CASRN=CAS)
                coeffs, (low, high), stats = obj.fit_polynomial(method, n=n, start_n=start_n, max_n=max_n_method, eval_pts=eval_pts)
                max_error = max(abs(1.0 - stats[2]), abs(1.0 - stats[3]))
                method_dat[CAS] = {'Tmax': high, 'Tmin': low, 'error_average': stats[0],
                   'error_std': stats[1], 'max_error': max_error , 'method': method,
                   'coefficients': coeffs}

            if save:
                f = open(os.path.join(folder, method + '_polyfits.json'), 'w')
                out_str = json.dumps(method_dat, sort_keys=True, indent=4, separators=(', ', ': '))
                f.write(out_str)
                f.close()
                dat[method] = method_dat

        return dat

    def fit_polynomial(self, method, n=None, start_n=3, max_n=30, eval_pts=100):
        r'''Method to fit a T-dependent property to a polynomial. The degree
        of the polynomial can be specified with the `n` parameter, or it will
        be automatically selected for maximum accuracy.

        Parameters
        ----------
        method : str
            Method name to fit, [-]
        n : int, optional
            The degree of the polynomial, if specified
        start_n : int
            If `n` is not specified, all polynomials of degree `start_n` to
            `max_n` will be tried and the highest-accuracy will be selected;
            [-]
        max_n : int
            If `n` is not specified, all polynomials of degree `start_n` to
            `max_n` will be tried and the highest-accuracy will be selected;
            [-]
        eval_pts : int
            The number of points to evaluate the fitted functions at to check
            for accuracy; more is better but slower, [-]

        Returns
        -------
        coeffs : list[float]
            Fit coefficients, [-]
        Tmin : float
            The minimum temperature used for the fitting, [K]
        Tmax : float
            The maximum temperature used for the fitting, [K]
        err_avg : float
            Mean error in the evaluated points, [-]
        err_std : float
            Standard deviation of errors in the evaluated points, [-]
        min_ratio : float
            Lowest ratio of calc/actual in any found points, [-]
        max_ratio : float
            Highest ratio of calc/actual in any found points, [-]
        '''
        # Ready to be documented
        from thermo.fitting import fit_cheb_poly, poly_fit_statistics, fit_cheb_poly_auto
        interpolation_property = self.interpolation_property
        interpolation_property_inv = self.interpolation_property_inv

        try:
            low, high = self.T_limits[method]
        except KeyError:
            raise ValueError("Unknown method")

        func = lambda T: self.calculate(T, method)

        if n is None:
            n, coeffs, stats = fit_cheb_poly_auto(func, low=low, high=high,
                      interpolation_property=interpolation_property,
                      interpolation_property_inv=interpolation_property_inv,
                      start_n=start_n, max_n=max_n, eval_pts=eval_pts)
        else:

            coeffs = fit_cheb_poly(func, low=low, high=high, n=n,
                          interpolation_property=interpolation_property,
                          interpolation_property_inv=interpolation_property_inv)

            stats = poly_fit_statistics(func, coeffs=coeffs, low=low, high=high, pts=eval_pts,
                          interpolation_property_inv=interpolation_property_inv)

        return coeffs, (low, high), stats
    
    def fit_add_model(self, name, model, Ts, data, **kwargs):
        r'''Method to add a new emperical fit equation to the object
        by fitting its coefficients to specified data.
        Once added, the new method is set as the default.

        A number of hardcoded `model` names are implemented; other models
        are not supported.
        
        This is a wrapper around :obj:`TDependentProperty.fit_data_to_model`
        and :obj:`TDependentProperty.add_correlation`.
        
        The data is also stored in the object as a tabular method with the name
        `name`+'_data', through
        :obj:`TDependentProperty.add_tabular_data`.

        Parameters
        ----------
        name : str
            The name of the coefficient set; user specified, [-]
        model : str
            A string representing the supported models, [-]
        Ts : list[float]
            Temperatures of the data points, [K]
        data : list[float]
            Data points, [`units`]
        kwargs : dict
            Various keyword arguments accepted by `fit_data_to_model`, [-]
        '''
        self.add_tabular_data(Ts=Ts, properties=data, name=name+'_data')
        fit = self.fit_data_to_model(Ts=Ts, data=data, model=model, **kwargs)
        self.add_correlation(name=name, model=model, Tmin=min(Ts), Tmax=max(Ts), **fit)
    
    @classmethod
    def fit_data_to_model(cls, Ts, data, model, model_kwargs=None, 
                          fit_method='lm', use_numba=False,
                          do_statistics=False, guesses=None,
                          solver_kwargs=None, objective='MeanSquareErr',
                          multiple_tries=False, multiple_tries_max_err=1e-5,
                          multiple_tries_max_objective='MeanRelErr'):
        r'''Method to fit T-dependent property data to one of the available
        model correlations. 

        Parameters
        ----------
        Ts : list[float]
            Temperatures of the data points, [K]
        data : list[float]
            Data points, [`units`]
        model : str
            A string representing the supported models, [-]
        model_kwargs : dict, optional
            Various keyword arguments accepted by the model; not necessary for 
            most models. Parameters which are normally fit, can be specified
            here as well with a constant value and then that fixed value will
            be used instead of fitting the parameter. [-]
        fit_method : str, optional
            The fit method to use; one of {`lm`, `trf`, `dogbox`, 
            `differential_evolution`}, [-]
        use_numba : bool, optional
            Whether or not to try to use numba to speed up the computation, [-]
        do_statistics : bool, optional
            Whether or not to compute statistical measures on the outputs, [-]
        guesses : dict[str: float], optional
            Parameter guesses, by name; any number of parameters can be
            specified, [-]
        solver_kwargs : dict
            Extra parameters to be passed to the solver chosen, [-]
        objective : str
            The minimimization criteria; supported by `differential_evolution`.
            One of:
            
            * 'MeanAbsErr': Mean absolute error
            * 'MeanRelErr': Mean relative error
            * 'MeanSquareErr': Mean squared absolute error
            * 'MeanSquareRelErr': Mean squared relative error
            * 'MaxAbsErr': Maximum absolute error
            * 'MaxRelErr': Maximum relative error
            * 'MaxSquareErr': Maximum squared absolute error
            * 'MaxSquareRelErr': Maximum squared relative error
        multiple_tries : bool or int
            For most solvers, multiple initial guesses are available and the best
            guess is normally tried. When this is set to True, all guesses are
            tried until one is found with an error lower than
            `multiple_tries_max_err`. If an int is supplied, the best `multiple_tries`
            guesses are tried only. [-]
        multiple_tries_max_err : float
            Only used when `multiple_tries` is true; if a solution is found
            with lower error than this, no further guesses are tried, [-]
        multiple_tries_max_objective : str
            The error criteria to use for minimization, [-]
            
        Returns
        -------
        coefficients : dict[str: float]
            Calculated coefficients, [`various`]
        statistics : dict[str: float]
            Statistics, calculated and returned only if `do_statistics` is True, [-]
        '''
        if use_numba:
            import thermo.numba, fluids.numba
            fit_func_dict = fluids.numba.numerics.fit_minimization_targets
        else:
            fit_func_dict = fit_minimization_targets
        if len(Ts) != len(data):
            raise ValueError("Length of data and temperatures is not the same")
        if model not in cls.available_correlations:
            raise ValueError("Model is not available; available models are %s" %(cls.available_correlations,))
        if model_kwargs is None:
            model_kwargs = {}
        if guesses is None:
            guesses = {}
        if solver_kwargs is None:
            solver_kwargs = {}
        if objective != 'MeanSquareErr' and fit_method != 'differential_evolution':
            raise ValueError("Specified objective is not supported with the specified solver")
        # if use_numba:
        # So long as the fitting things happen with scipy, arrays are needed
        Ts = np.array(Ts)
        data = np.array(data)
        
        required_args, optional_args, functions, fit_data = cls.correlation_models[model]
        fit_parameters = fit_data['fit_params']
        all_fit_parameters = fit_parameters
        
        use_fit_parameters = []
        for k in fit_parameters:
            if k not in model_kwargs:
                use_fit_parameters.append(k)
        fit_parameters = use_fit_parameters
            
        param_order = required_args + optional_args
        const_kwargs = {}
        model_function_name = functions['f'].__name__

        for k in required_args:
            if k not in model_kwargs and k not in use_fit_parameters:
                raise ValueError("The selected model requires an input parameter {}".format(k))
        do_minimization = fit_method == 'differential_evolution'
        fitting_func = generate_fitting_function(model_function_name, param_order,
                              fit_parameters, all_fit_parameters, model_kwargs, const_kwargs, try_numba=use_numba)

        err_func = fit_func_dict[objective]
        err_fun_multiple_guesses = fit_func_dict[multiple_tries_max_objective]
        
        if do_minimization:
            def minimize_func(params):
                calc = fitting_func(Ts, *params)
                err = err_func(data, calc)
                return err
            
        p0 = [1.0]*len(fit_parameters)
        if guesses:
            for i, k in enumerate(use_fit_parameters):
                if k in guesses:
                    p0[i] = guesses[k]
                    
        if 'initial_guesses' in fit_data:
            # iterate over all the initial guess parameters we have and find the one
            # with the lowest error (according to the error criteria)
            best_hardcoded_guess = None
            best_hardcoded_err = 1e300
            hardcoded_errors = []
            hardcoded_guesses = fit_data['initial_guesses']
            extra_user_guess = [{k: v for k, v in zip(use_fit_parameters, p0)}]
            all_iter_guesses = hardcoded_guesses + extra_user_guess
            array_init_guesses = []
            err_func_init = fit_func_dict['MeanRelErr']
            for hardcoded in all_iter_guesses:
                ph = [None]*len(fit_parameters)
                for i, k in enumerate(use_fit_parameters):
                    ph[i] = hardcoded[k]
                array_init_guesses.append(ph)
                
                calc = fitting_func(Ts, *ph)
                err = err_func_init(data, calc)
                hardcoded_errors.append(err)
                if err < best_hardcoded_err:
                    best_hardcoded_err = err
                    best_hardcoded_guess = ph
            p0 = best_hardcoded_guess
            array_init_guesses = [p0 for _, p0 in sorted(zip(hardcoded_errors, array_init_guesses))]
        else:
            array_init_guesses = [p0]
        
        if 'fit_jac' in fit_data:
            analytical_jac_coded = fit_data['fit_jac']
            # if fit_data['fit_params'] != use_fit_parameters:
            # else:
            analytical_jac = generate_fitting_function(model_function_name, param_order,
                                                     fit_parameters, all_fit_parameters, model_kwargs, const_kwargs,
                                                     try_numba=use_numba, jac=True)
        else:
            analytical_jac = None

        def func_wrapped_for_leastsq(params):
            # jacobian is the same
            return fitting_func(Ts, *params) - data

        def jac_wrapped_for_leastsq(params):
            return analytical_jac(Ts, *params)

        pcov = None
        if fit_method == 'differential_evolution':
            if 'bounds' in solver_kwargs:
                working_bounds = solver_kwargs.pop('bounds')
            else:
                try:
                    bounds = fit_data['bounds']
                    working_bounds = [bounds[k] for k in use_fit_parameters]
                except KeyError:
                    factor = 4.0
                    if len(array_init_guesses) > 3:
                        lowers_guess, uppers_guess = np.array(array_init_guesses).min(axis=0), np.array(array_init_guesses).max(axis=0)
                        working_bounds = [(lowers_guess[i]*factor if lowers_guess[i] < 0. else lowers_guess[i]*(1.0/factor),
                                           uppers_guess[i]*(1.0/factor) if uppers_guess[i] < 0. else uppers_guess[i]*(factor),
                                           ) for i in range(len(use_fit_parameters))]
                    else:
                        working_bounds = [(-1e30, 1e30) for k in use_fit_parameters]
            popsize = solver_kwargs.get('popsize', 15)*len(fit_parameters)
            init = array_init_guesses
            for i in range(len(init), popsize):
                to_add = [uniform(ll, lh) for ll, lh in working_bounds]
                init.append(to_add)
                
            res = differential_evolution(minimize_func, init=np.array(init),
                                         bounds=working_bounds, **solver_kwargs)
            popt = res['x']
        else:
            lm_direct = fit_method == 'lm'
            Dfun = jac_wrapped_for_leastsq if analytical_jac is not None else None
            if 'maxfev' not in solver_kwargs and fit_method == 'lm':
                # DO NOT INCREASE THIS! Make an analytical jacobian instead please.
                # Fought very hard to bring the analytical jacobian maxiters down to 500!
                # 250 seems too small.
                if analytical_jac is not None:
                    solver_kwargs['maxfev'] = 500
                else:
                    solver_kwargs['maxfev'] = 5000 
            if multiple_tries:
                multiple_tries_best_error = 1e300
                best_popt, best_pcov = None, None
                popt = None
                if type(multiple_tries) is int and len(array_init_guesses) > multiple_tries:
                    array_init_guesses = array_init_guesses[0:multiple_tries]
                for p0 in array_init_guesses:
                    try:
                        if lm_direct:
                            popt, _ = leastsq(func_wrapped_for_leastsq, p0, Dfun=Dfun, **solver_kwargs)
                            pcov = None
                        else:
                            popt, pcov = curve_fit(fitting_func, Ts, data, p0=p0, jac=analytical_jac, 
                                                   method=fit_method, **solver_kwargs)
                    except:
                        continue
                    calc = fitting_func(Ts, *popt)
                    curr_err = err_fun_multiple_guesses(data, calc)
                    if curr_err < multiple_tries_best_error:
                        best_popt, best_pcov = popt, pcov
                        multiple_tries_best_error = curr_err
                        if curr_err < multiple_tries_max_err:
                            break
                    
                if best_popt is None:
                    raise ValueError("No guesses converged")
                else:
                    popt, pcov = best_popt, best_pcov
            else:
                if lm_direct:
                    popt, _ = leastsq(func_wrapped_for_leastsq, p0, Dfun=Dfun, **solver_kwargs)
                    pcov = None
                else:
                    popt, pcov = curve_fit(fitting_func, Ts, data, p0=p0, jac=analytical_jac,
                                           method=fit_method, **solver_kwargs)
        out_kwargs = model_kwargs.copy()
        for param_name, param_value in zip(fit_parameters, popt):
            out_kwargs[param_name] = float(param_value)

        if do_statistics:
            if not use_numba:
                stats_func = data_fit_statistics 
            else:
                stats_func = thermo.numba.fitting.data_fit_statistics
            calc = fitting_func(Ts, *popt)
            stats = stats_func(Ts, data, calc)
            statistics = {}
            statistics['calc'] = calc
            statistics['MAE'] = stats[0]
            statistics['STDEV'] = stats[1]
            statistics['min_ratio'] = stats[2]
            statistics['max_ratio'] = stats[3]
            statistics['pcov'] = pcov
            return out_kwargs, statistics


        return out_kwargs

    @property
    def method(self):
        r'''Method used to set a specific property method or to obtain the name
        of the method in use.

        When setting a method, an exception is raised if the method specified
        isnt't available for the chemical with the provided information.

        If `method` is None, no calculations can be performed.

        Parameters
        ----------
        method : str
            Method to use, [-]
        '''
        return self._method

    @method.setter
    def method(self, method):
        if method not in self.all_methods and method != POLY_FIT and method is not None:
            raise ValueError("The given method is not available for this chemical")
        self.T_cached = None
        self._method = method

    def valid_methods(self, T=None):
        r'''Method to obtain a sorted list of methods that have data
        available to be used. The methods are ranked in the following order:

        * The currently selected method is first (if one is selected)
        * Other available methods are ranked by the attribute :obj:`ranked_methods`

        If `T` is provided, the methods will be checked against the temperature
        limits of the correlations as well.

        Parameters
        ----------
        T : float or None
            Temperature at which to test methods, [K]

        Returns
        -------
        sorted_valid_methods : list
            Sorted lists of methods valid at T according to
            :obj:`test_method_validity`, [-]
        '''
        all_methods = self.all_methods
        sorted_methods = [i for i in self.ranked_methods if i in all_methods]
        current_method = self.method
        if current_method in sorted_methods:
            # Add back the user's methods to the top, in order.
            sorted_methods.remove(current_method)
            sorted_methods.insert(0, current_method)
        if T is not None:
            sorted_methods = [i for i in sorted_methods
                              if self.test_method_validity(T, i)]
        return sorted_methods

    @classmethod
    def test_property_validity(self, prop):
        r'''Method to test the validity of a calculated property. Normally,
        this method is used by a given property class, and has maximum and
        minimum limits controlled by the variables :obj:`property_min` and
        :obj:`property_max`.

        Parameters
        ----------
        prop : float
            property to be tested, [`units`]

        Returns
        -------
        validity : bool
            Whether or not a specifid method is valid
        '''
        if isinstance(prop, complex):
            return False
        elif prop < self.property_min:
            return False
        elif prop > self.property_max:
            return False
        return True

    def _custom_set_poly_fit(self):
        pass

    def _set_poly_fit(self, poly_fit, set_limits=False):
        if (poly_fit is not None and len(poly_fit) and (poly_fit[0] is not None
           and poly_fit[1] is not None and  poly_fit[2] is not None)
            and not isnan(poly_fit[0]) and not isnan(poly_fit[1])):
            self.poly_fit_Tmin = Tmin = poly_fit[0]
            self.poly_fit_Tmax = Tmax = poly_fit[1]
            self.poly_fit_coeffs = poly_fit_coeffs = poly_fit[2]
            self.T_limits[POLY_FIT] = (Tmin, Tmax)

            self.poly_fit_int_coeffs = polyint(poly_fit_coeffs)
            self.poly_fit_T_int_T_coeffs, self.poly_fit_log_coeff = polyint_over_x(poly_fit_coeffs)

            poly_fit_d_coeffs = polyder(poly_fit_coeffs[::-1])
            self.poly_fit_d2_coeffs = polyder(poly_fit_d_coeffs)
            self.poly_fit_d2_coeffs.reverse()
            self.poly_fit_d_coeffs = poly_fit_d_coeffs
            poly_fit_d_coeffs.reverse()

            # Extrapolation slope on high and low
            slope_delta_T = (self.poly_fit_Tmax - self.poly_fit_Tmin)*.05

            self.poly_fit_Tmax_value = self.calculate(self.poly_fit_Tmax, POLY_FIT)
            if self.interpolation_property is not None:
                self.poly_fit_Tmax_value = self.interpolation_property(self.poly_fit_Tmax_value)


            # Calculate the average derivative for the last 5% of the curve
#            fit_value_high = self.calculate(self.poly_fit_Tmax - slope_delta_T, POLY_FIT)
#            if self.interpolation_property is not None:
#                fit_value_high = self.interpolation_property(fit_value_high)

#            self.poly_fit_Tmax_slope = (self.poly_fit_Tmax_value
#                                        - fit_value_high)/slope_delta_T
            self.poly_fit_Tmax_slope = horner(self.poly_fit_d_coeffs, self.poly_fit_Tmax)
            self.poly_fit_Tmax_dT2 = horner(self.poly_fit_d2_coeffs, self.poly_fit_Tmax)


            # Extrapolation to lower T
            self.poly_fit_Tmin_value = self.calculate(self.poly_fit_Tmin, POLY_FIT)
            if self.interpolation_property is not None:
                self.poly_fit_Tmin_value = self.interpolation_property(self.poly_fit_Tmin_value)

#            fit_value_low = self.calculate(self.poly_fit_Tmin + slope_delta_T, POLY_FIT)
#            if self.interpolation_property is not None:
#                fit_value_low = self.interpolation_property(fit_value_low)
#            self.poly_fit_Tmin_slope = (fit_value_low
#                                        - self.poly_fit_Tmin_value)/slope_delta_T

            self.poly_fit_Tmin_slope = horner(self.poly_fit_d_coeffs, self.poly_fit_Tmin)
            self.poly_fit_Tmin_dT2 = horner(self.poly_fit_d2_coeffs, self.poly_fit_Tmin)

            self._custom_set_poly_fit()

            if set_limits:
                if self.Tmin is None:
                    self.Tmin = self.poly_fit_Tmin
                if self.Tmax is None:
                    self.Tmax = self.poly_fit_Tmax

    def as_poly_fit(self):
        return '%s(load_data=False, poly_fit=(%s, %s, %s))' %(self.__class__.__name__,
                  repr(self.poly_fit_Tmin), repr(self.poly_fit_Tmax),
                  repr(self.poly_fit_coeffs))

    def _base_calculate(self, T, method):
        if method in self.tabular_data:
            return self.interpolate(T, method)
        elif method in self.local_methods:
            return self.local_methods[method].f(T)
        elif method in self.correlations:
            call, kwargs, _ = self.correlations[method]
            return call(T, **kwargs)
        else:
            raise ValueError("Unknown method; methods are %s" %(self.all_methods))

    def _base_calculate_P(self, T, P, method):
        if method in self.tabular_data_P:
            return self.interpolate_P(T, P, method)
        else:
            raise ValueError("Unknown method")

    def _calculate_extrapolate(self, T, method):
        if method == POLY_FIT:
            try: return self.calculate(T, POLY_FIT)
            except: return None

        if method is None:
            return None
        try:
            T_low, T_high = self.T_limits[method]
            in_range = T_low <= T <= T_high
        except KeyError:
            in_range = self.test_method_validity(T, method)

        if in_range:
            try:
                prop = self.calculate(T, method)
            except:
                return None
            if self.test_property_validity(prop):
                return prop
        elif self._extrapolation is not None:
            try:
                return self.extrapolate(T, method)
            except:
                return None
        # Function returns None if it does not work.
        return None

    def T_dependent_property(self, T):
        r'''Method to calculate the property with sanity checking and using
        the selected :obj:`method <thermo.utils.TDependentProperty.method>`.

        In the unlikely event the calculation of the property fails, None
        is returned.

        The calculated result is checked with
        :obj:`test_property_validity <thermo.utils.TDependentProperty.test_property_validity>`
        and None is returned if the calculated value is nonsensical.

        Parameters
        ----------
        T : float
            Temperature at which to calculate the property, [K]

        Returns
        -------
        prop : float
            Calculated property, [`units`]
        '''
        method = self._method
        if method == POLY_FIT:
            # There is no use case where this will fail; it is designed to 
            # always calculate a value
            return self.calculate(T, POLY_FIT)
        elif method is None:
            if self.RAISE_PROPERTY_CALCULATION_ERROR: 
                raise RuntimeError("No %s method selected for component with CASRN '%s'" %(self.name.lower(), self.CASRN))
        else:
            try:
                T_low, T_high = self.T_limits[method]
                in_range = T_low <= T <= T_high
            except KeyError:
                in_range = self.test_method_validity(T, method)
            if in_range:
                try: prop = self.calculate(T, method)
                except: 
                    if self.RAISE_PROPERTY_CALCULATION_ERROR:
                        raise RuntimeError("Failed to evaluate %s method '%s' at T=%s K for component with CASRN '%s'" %(self.name.lower(), method, T, self.CASRN))
                else:
                    if self.test_property_validity(prop):
                        return prop
                    elif self.RAISE_PROPERTY_CALCULATION_ERROR:
                        raise RuntimeError("%s method '%s' computed an invalid value of %s %s for component with CASRN '%s'" %(self.name, method, prop, self.units, self.CASRN))
            elif self._extrapolation is not None:
                try:
                    return self.extrapolate(T, method)
                except:
                    if self.RAISE_PROPERTY_CALCULATION_ERROR:
                        raise RuntimeError("Failed to extrapolate %s method '%s' at T=%s K for component with CASRN '%s'" %(self.name.lower(), method, T, self.CASRN))
            elif self.RAISE_PROPERTY_CALCULATION_ERROR: 
                raise RuntimeError("%s method '%s' is not valid at T=%s K for component with CASRN '%s'" %(self.name, method, T, self.CASRN))

    def plot_T_dependent_property(self, Tmin=None, Tmax=None, methods=[],
                                  pts=250, only_valid=True, order=0, show=True,
                                  axes='semilogy'):
        r'''Method to create a plot of the property vs temperature according to
        either a specified list of methods, or user methods (if set), or all
        methods. User-selectable number of points, and temperature range. If
        only_valid is set,:obj:`test_method_validity` will be used to check if each
        temperature in the specified range is valid, and
        :obj:`test_property_validity` will be used to test the answer, and the
        method is allowed to fail; only the valid points will be plotted.
        Otherwise, the result will be calculated and displayed as-is. This will
        not suceed if the method fails.

        Parameters
        ----------
        Tmin : float
            Minimum temperature, to begin calculating the property, [K]
        Tmax : float
            Maximum temperature, to stop calculating the property, [K]
        methods : list, optional
            List of methods to consider
        pts : int, optional
            A list of points to calculate the property at; if Tmin to Tmax
            covers a wide range of method validities, only a few points may end
            up calculated for a given method so this may need to be large
        only_valid : bool
            If True, only plot successful methods and calculated properties,
            and handle errors; if False, attempt calculation without any
            checking and use methods outside their bounds
        show : bool
            If True, displays the plot; otherwise, returns it
        '''
        # This function cannot be tested
        if not has_matplotlib():
            raise Exception('Optional dependency matplotlib is required for plotting')
        if not methods:
            methods = self.all_methods
        if Tmin is None:
            T_limits = self.T_limits
            Tmin = min(T_limits[m][0] for m in methods)
        if Tmax is None:
            T_limits = self.T_limits
            Tmax = min(T_limits[m][1] for m in methods)
        import matplotlib.pyplot as plt

            
        tabular_data = self.tabular_data

#        cm = plt.get_cmap('gist_rainbow')
        fig = plt.figure()
#        ax = fig.add_subplot(111)
#        NUM_COLORS = len(methods)
#        ax.set_color_cycle([cm(1.*i/NUM_COLORS) for i in range(NUM_COLORS)])

        plot_fun = {'semilogy': plt.semilogy, 'semilogx': plt.semilogx, 'plot': plt.plot}[axes]
        Ts = linspace(Tmin, Tmax, pts)
        if order == 0:
            for method in methods:
                fmt = '-'
                if method in tabular_data:
                    fmt = 'x'
                
                if only_valid:
                    properties, Ts2 = [], []
                    for T in Ts:
                        if self.test_method_validity(T, method):
                            try:
                                p = self._calculate_extrapolate(T=T, method=method)
                                if self.test_property_validity(p):
                                    properties.append(p)
                                    Ts2.append(T)
                            except:
                                pass
                    plot_fun(Ts2, properties, fmt, label=method)
                else:
                    properties = [self._calculate_extrapolate(T=T, method=method) for T in Ts]
                    plot_fun(Ts, properties, fmt, label=method)
            plt.ylabel(self.name + ', ' + self.units)
            title = self.name
            if self.CASRN:
                title += ' of ' + self.CASRN
            plt.title(title)
        elif order > 0:
            for method in methods:
                if only_valid:
                    properties, Ts2 = [], []
                    for T in Ts:
                        if self.test_method_validity(T, method):
                            try:
                                p = self.calculate_derivative(T=T, method=method, order=order)
                                properties.append(p)
                                Ts2.append(T)
                            except:
                                pass
                    plot_fun(Ts2, properties, label=method)
                else:
                    properties = [self.calculate_derivative(T=T, method=method, order=order) for T in Ts]
                    plot_fun(Ts, properties, label=method)
            plt.ylabel(self.name + ', ' + self.units + '/K^%d derivative of order %d' % (order, order))

            title = self.name + ' derivative of order %d' % order
            if self.CASRN:
                title += ' of ' + self.CASRN
            plt.title(title)
        plt.legend(loc='best', fancybox=True, framealpha=0.5)
        plt.xlabel('Temperature, K')
        if show:
            plt.show()
        else:
            return plt

    def interpolate(self, T, name):
        r'''Method to perform interpolation on a given tabular data set
        previously added via :obj:`add_tabular_data`. This method will create the
        interpolators the first time it is used on a property set, and store
        them for quick future use.

        Interpolation is cubic-spline based if 5 or more points are available,
        and linearly interpolated if not. Extrapolation is always performed
        linearly. This function uses the transforms :obj:`interpolation_T`,
        :obj:`interpolation_property`, and :obj:`interpolation_property_inv` if set. If
        any of these are changed after the interpolators were first created,
        new interpolators are created with the new transforms.
        All interpolation is performed via the `interp1d` function.

        Parameters
        ----------
        T : float
            Temperature at which to interpolate the property, [K]
        name : str
            The name assigned to the tabular data set

        Returns
        -------
        prop : float
            Calculated property, [`units`]
        '''
        # Cannot use method as key - need its id; faster also
        key = (name, id(self.interpolation_T), id(self.interpolation_property), id(self.interpolation_property_inv))

        # If the interpolator and extrapolator has already been created, load it
#        if isinstance(self.tabular_data_interpolators, dict) and key in self.tabular_data_interpolators:
#            extrapolator, spline = self.tabular_data_interpolators[key]

        if key in self.tabular_data_interpolators:
            extrapolator, spline = self.tabular_data_interpolators[key]
        else:
            from scipy.interpolate import interp1d
            Ts, properties = self.tabular_data[name]

            if self.interpolation_T is not None:  # Transform ths Ts with interpolation_T if set
                Ts_interp = [self.interpolation_T(T) for T in Ts]
            else:
                Ts_interp = Ts
            if self.interpolation_property is not None:  # Transform ths props with interpolation_property if set
                properties_interp = [self.interpolation_property(p) for p in properties]
            else:
                properties_interp = properties
            # Only allow linear extrapolation, but with whatever transforms are specified
            extrapolator = interp1d(Ts_interp, properties_interp, fill_value='extrapolate')
            # If more than 5 property points, create a spline interpolation
            if len(properties) >= 5:
                spline = interp1d(Ts_interp, properties_interp, kind='cubic')
            else:
                spline = None
#            if isinstance(self.tabular_data_interpolators, dict):
#                self.tabular_data_interpolators[key] = (extrapolator, spline)
#            else:
#                self.tabular_data_interpolators = {key: (extrapolator, spline)}
            self.tabular_data_interpolators[key] = (extrapolator, spline)

        # Load the stores values, tor checking which interpolation strategy to
        # use.
        Ts, properties = self.tabular_data[name]

        if T < Ts[0] or T > Ts[-1] or not spline:
            tool = extrapolator
        else:
            tool = spline

        if self.interpolation_T:
            T = self.interpolation_T(T)
        prop = tool(T)  # either spline, or linear interpolation

        if self.interpolation_property:
            prop = self.interpolation_property_inv(prop)

        return float(prop)
    

    def add_correlation(self, name, model, Tmin, Tmax, **kwargs):
        r'''Method to add a new set of emperical fit equation coefficients to
        the object and select it for future property calculations.

        A number of hardcoded `model` names are implemented; other models
        are not supported.

        Parameters
        ----------
        name : str
            The name of the coefficient set; user specified, [-]
        model : str
            A string representing the supported models, [-]
        Tmin : float
            Minimum temperature to use the method at, [K]
        Tmax : float
            Maximum temperature to use the method at, [K]
        kwargs : dict
            Various keyword arguments accepted by the model, [-]

        Notes
        -----
        The correlation models and links to their functions, describing
        their parameters, are as follows:

        '''
        if model not in self.available_correlations:
            raise ValueError("Model is not available; available models are %s" %(self.available_correlations,))
        model_data = self.correlation_models[model]
        if not all(k in kwargs and kwargs[k] is not None for k in model_data[0]):
            raise ValueError("Required arguments for this model are %s" %(model_data[0],))
        if name in self.all_methods:
            raise ValueError("Provided method is already a method")

        model_kwargs = {k: kwargs[k] for k in model_data[0]}
        for param in model_data[1]:
            if param in kwargs:
                model_kwargs[param] = kwargs[param]

        d = getattr(self, model + '_parameters', None)
        if d is None:
            d = {}
            setattr(self, model + '_parameters', d)

        full_kwargs = model_kwargs.copy()
        full_kwargs['Tmax'] = Tmax
        full_kwargs['Tmin'] = Tmin
        d[name] = full_kwargs

        self.T_limits[name] = (Tmin, Tmax)
        self.all_methods.add(name)

        call = self.correlation_models[model][2]['f']
        self.correlations[name] = (call, model_kwargs, model)
        self.method = name

    try:
        _text = '\n'
        for correlation_name, _correlation_parameters in correlation_models.items():
            f = _correlation_parameters[2]['f']
            correlation_func_name = f.__name__
            correlation_func_mod = f.__module__
            s = '        * "%s": :obj:`%s <%s.%s>`, required parameters %s' %(correlation_name, correlation_func_name, correlation_func_mod, correlation_func_name, tuple(_correlation_parameters[0]))
            if _correlation_parameters[1]:
                s += ', optional parameters %s.\n' %(tuple(_correlation_parameters[1]),)
            else:
                s += '.\n'
            _text += s
        add_correlation.__doc__ += _text
    except: 
        pass

    def add_method(self, f, Tmin=None, Tmax=None,
                   f_der=None, f_der2=None, f_der3=None,
                   f_int=None, f_int_over_T=None, name=None):
        r'''Define a new method and select it for future property
        calculations.

        Parameters
        ----------
        f : callable
            Object which calculates the property given the temperature in K,
            [-]
        Tmin : float, optional
            Minimum temperature to use the method at, [K]
        Tmax : float, optional
            Maximum temperature to use the method at, [K]
        f_der : callable, optional
            If specified, should take as an argument the temperature and
            return the first derivative of the property, [-]
        f_der2 : callable, optional
            If specified, should take as an argument the temperature and
            return the second derivative of the property, [-]
        f_der3 : callable, optional
            If specified, should take as an argument the temperature and
            return the third derivative of the property, [-]
        f_int : callable, optional
            If specified, should take `T1` and `T2` and return the integral of
            the property from `T1` to `T2`, [-]
        f_int_over_T : callable, optional
            If specified, should take `T1` and `T2` and return the integral of
            the property over T from `T1` to `T2`, [-]
        name : str, optional
            Name of method.

        Notes
        -----
        Once a custom method has been added to an object, that object can no
        longer be serialized to json and the :obj:`TDependentProperty.__repr__`
        method can no longer be used to reconstruct the object completely.

        '''
        local_methods = self.local_methods
        if name is None: name = 'USER_METHOD'
        local_methods[name] = create_local_method(f, f_der, f_der2, f_der3,
                                                  f_int, f_int_over_T)
        self._method = name
        self.T_cached = None
        self.all_methods.add(name)
        self.T_limits[name] = (0. if Tmin is None else Tmin,
                               inf if Tmax is None else Tmax)

    def add_tabular_data(self, Ts, properties, name=None, check_properties=True):
        r'''Method to set tabular data to be used for interpolation.
        Ts must be in increasing order. If no name is given, data will be
        assigned the name 'Tabular data series #x', where x is the number of
        previously added tabular data series.

        After adding the data, this method becomes the selected method.

        Parameters
        ----------
        Ts : array-like
            Increasing array of temperatures at which properties are specified, [K]
        properties : array-like
            List of properties at Ts, [`units`]
        name : str, optional
            Name assigned to the data
        check_properties : bool
            If True, the properties will be checked for validity with
            :obj:`test_property_validity` and raise an exception if any are not
            valid
        '''
        # Ts must be in increasing order.
        if check_properties:
            for p in properties:
                if not self.test_property_validity(p):
                    raise ValueError('One of the properties specified are not feasible')
        if not all(b > a for a, b in zip(Ts, Ts[1:])):
            raise ValueError('Temperatures are not sorted in increasing order')

        if name is None:
            name = 'Tabular data series #' + str(len(self.tabular_data))  # Will overwrite a poorly named series
        self.tabular_data[name] = (Ts, properties)
        self.T_limits[name] = (min(Ts), max(Ts))

        self.all_methods.add(name)
        self.method = name

    def solve_property(self, goal):
        r'''Method to solve for the temperature at which a property is at a
        specified value. :obj:`T_dependent_property <thermo.utils.TDependentProperty.T_dependent_property>` is used to calculate the value
        of the property as a function of temperature.

        Checks the given property value with :obj:`test_property_validity` first
        and raises an exception if it is not valid.

        Parameters
        ----------
        goal : float
            Propoerty value desired, [`units`]

        Returns
        -------
        T : float
            Temperature at which the property is the specified value [K]
        '''
        if not self.test_property_validity(goal):
            raise ValueError('Input property is not considered plausible; no method would calculate it.')

        def error(T):
            err = self.T_dependent_property(T) - goal
            return err
        T_limits = self.T_limits[self.method]
        if self.extrapolation is None:
            try:
                return brenth(error, T_limits[0], T_limits[1])
            except ValueError:
                raise Exception('To within the implemented temperature range, it is not possible to calculate the desired value.')
        else:
            high = self.Tc if self.critical_zero and self.Tc is not None else None
            x0 = T_limits[0]
            x1 = T_limits[1]
            f0 = error(x0)
            f1 = error(x1)
            if f0*f1 > 0.0: # same sign, pick which side to start the search at based on which error is lower
                if abs(f0) < abs(f1):
                    # under Tmin
                    x1 = T_limits[0] - (T_limits[1] - T_limits[0])*1e-3
                    f1 = error(x1)
                else:
                    # above Tmax
                    x0 = T_limits[1] + (T_limits[1] - T_limits[0])*1e-3
                    if high is not None and x0 > high:
                        x0 = high*(1-1e-6)
                    f0 = error(x0)
            #try:
            return secant(error, x0=x0, x1=x1, f0=f0, f1=f1, low=1e-4, xtol=1e-12, bisection=True, high=high)
            #except:
            #    return secant(error, x0=x0, x1=x1, f0=f0, f1=f1, low=1e-4, xtol=1e-12, bisection=True, high=high, damping=.01)

    def _calculate_derivative_transformed(self, T, method, order=1):
        r'''Basic funtion which wraps calculate_derivative such that the output
        of the derivative is in the transformed basis.'''
        if self.interpolation_property is None and self.interpolation_T is None:
            return self.calculate_derivative(T, method, order=1)

        interpolation_T = self.interpolation_T
        if interpolation_T is None:
            interpolation_T = lambda T: T
        interpolation_property = self.interpolation_property
        if interpolation_property is None:
            interpolation_property = lambda x: x

        try:
            return derivative(lambda T_trans: (interpolation_property(self.calculate(interpolation_T(T_trans), method=method))),
                              interpolation_T(T), dx=interpolation_T(T)*1e-6, n=order, order=1+order*2)
        except:
            Tmin, Tmax = self.T_limits[method]
            Tmin_trans, Tmax_trans = interpolation_T(Tmin), interpolation_T(Tmax)
            lower_limit = min(Tmin_trans, Tmax_trans)
            upper_limit = max(Tmin_trans, Tmax_trans)

            return derivative(lambda T_trans: interpolation_property(self.calculate(interpolation_T(T_trans), method=method)),
                              interpolation_T(T),
                              dx=interpolation_T(T)*1e-6, n=order, order=1+order*2,
                              lower_limit=lower_limit, upper_limit=upper_limit)

    def calculate_derivative(self, T, method, order=1):
        r'''Method to calculate a derivative of a property with respect to
        temperature, of a given order  using a specified method. Uses SciPy's
        derivative function, with a delta of 1E-6 K and a number of points
        equal to 2*order + 1.

        This method can be overwritten by subclasses who may perfer to add
        analytical methods for some or all methods as this is much faster.

        If the calculation does not succeed, returns the actual error
        encountered.

        Parameters
        ----------
        T : float
            Temperature at which to calculate the derivative, [K]
        method : str
            Method for which to find the derivative
        order : int
            Order of the derivative, >= 1

        Returns
        -------
        derivative : float
            Calculated derivative property, [`units/K^order`]
        '''
        if method in self.correlations:
            _, model_kwargs, model = self.correlations[method]
            calls = self.correlation_models[model][2]
            if order == 1 and 'f_der' in calls:
                return calls['f_der'](T, **model_kwargs)
            elif order == 2 and 'f_der2' in calls:
                return calls['f_der2'](T, **model_kwargs)
            elif order == 3 and 'f_der3' in calls:
                return calls['f_der3'](T, **model_kwargs)
        
        Tmin, Tmax = self.T_limits[method]
        in_range = Tmin <= T <= Tmax
        if method in self.local_methods and in_range:
            local_method = self.local_methods[method]
            if order == 1:
                if local_method.f_der is not None: return local_method.f_der(T)
            elif order == 2:
                if local_method.f_der2 is not None: return local_method.f_der2(T)
            elif order == 3:
                if local_method.f_der3 is not None: return local_method.f_der3(T)
        pts = 1 + order*2
        dx = T*1e-6
        args = (method,)
        if in_range:
            # Adjust to be just inside bounds
            return derivative(self.calculate, T, dx=dx, args=args, n=order, order=pts,
                              lower_limit=Tmin, upper_limit=Tmax)
        elif self._extrapolation is not None:
            # Allow extrapolation
            return derivative(self.extrapolate, T, dx=dx, args=args, n=order, order=pts)
        else:
            raise ValueError("temperature is outside the valid range")
#

    def T_dependent_property_derivative(self, T, order=1):
        r'''Method to obtain a derivative of a property with respect to
        temperature, of a given order.

        Calls :obj:`calculate_derivative` internally to perform the actual
        calculation.

        .. math::
            \text{derivative} = \frac{d (\text{property})}{d T}

        Parameters
        ----------
        T : float
            Temperature at which to calculate the derivative, [K]
        order : int
            Order of the derivative, >= 1

        Returns
        -------
        derivative : float
            Calculated derivative property, [`units/K^order`]
        '''
        return self.calculate_derivative(T, self._method, order)

    def calculate_integral(self, T1, T2, method):
        r'''Method to calculate the integral of a property with respect to
        temperature, using a specified method. Uses SciPy's `quad` function
        to perform the integral, with no options.

        This method can be overwritten by subclasses who may perfer to add
        analytical methods for some or all methods as this is much faster.

        If the calculation does not succeed, returns the actual error
        encountered.

        Parameters
        ----------
        T1 : float
            Lower limit of integration, [K]
        T2 : float
            Upper limit of integration, [K]
        method : str
            Method for which to find the integral

        Returns
        -------
        integral : float
            Calculated integral of the property over the given range,
            [`units*K`]
        '''
        if method in self.correlations:
            _, model_kwargs, model = self.correlations[method]
            calls = self.correlation_models[model][2]
            if 'f_int' in calls:
                return calls['f_int'](T2, **model_kwargs) - calls['f_int'](T1, **model_kwargs)
        if method in self.local_methods:
            local_method = self.local_methods[method]
            if local_method.f_int is not None:
                return local_method.f_int(T1, T2)
        return float(quad(self.calculate, T1, T2, args=(method,))[0])

    def T_dependent_property_integral(self, T1, T2):
        r'''Method to calculate the integral of a property with respect to
        temperature, using the selected method.

        Calls :obj:`calculate_integral` internally to perform the actual
        calculation.

        .. math::
            \text{integral} = \int_{T_1}^{T_2} \text{property} \; dT

        Parameters
        ----------
        T1 : float
            Lower limit of integration, [K]
        T2 : float
            Upper limit of integration, [K]

        Returns
        -------
        integral : float
            Calculated integral of the property over the given range,
            [`units*K`]
        '''
        try:
            return self.calculate_integral(T1, T2, self._method)
        except:
            pass
        return None

    def calculate_integral_over_T(self, T1, T2, method):
        r'''Method to calculate the integral of a property over temperature
        with respect to temperature, using a specified method. Uses SciPy's
        `quad` function to perform the integral, with no options.

        This method can be overwritten by subclasses who may perfer to add
        analytical methods for some or all methods as this is much faster.

        If the calculation does not succeed, returns the actual error
        encountered.

        Parameters
        ----------
        T1 : float
            Lower limit of integration, [K]
        T2 : float
            Upper limit of integration, [K]
        method : str
            Method for which to find the integral

        Returns
        -------
        integral : float
            Calculated integral of the property over the given range,
            [`units`]
        '''
        if method in self.correlations:
            _, model_kwargs, model = self.correlations[method]
            calls = self.correlation_models[model][2]
            if 'f_int_over_T' in calls:
                return calls['f_int_over_T'](T2, **model_kwargs) - calls['f_int_over_T'](T1, **model_kwargs)
        if method in self.local_methods:
            local_method = self.local_methods[method]
            if local_method.f_int_over_T is not None:
                return local_method.f_int_over_T(T1, T2)
        return float(quad(lambda T: self.calculate(T, method)/T, T1, T2)[0])

    def T_dependent_property_integral_over_T(self, T1, T2):
        r'''Method to calculate the integral of a property over temperature
        with respect to temperature, using the selected method.

        Calls :obj:`calculate_integral_over_T` internally to perform the actual
        calculation.

        .. math::
            \text{integral} = \int_{T_1}^{T_2} \frac{\text{property}}{T} \; dT

        Parameters
        ----------
        T1 : float
            Lower limit of integration, [K]
        T2 : float
            Upper limit of integration, [K]

        Returns
        -------
        integral : float
            Calculated integral of the property over the given range,
            [`units`]
        '''
        try:
            return self.calculate_integral_over_T(T1, T2, self._method)
        except:
            pass
        return None

    def _get_extrapolation_coeffs(self, extrapolation, method):
        T_limits = self.T_limits
        if extrapolation == 'linear':
            interpolation_T = self.interpolation_T
            interpolation_property = self.interpolation_property
            interpolation_property_inv = self.interpolation_property_inv
            Tmin, Tmax = T_limits[method]
            if interpolation_T is not None:
                Tmin_trans, Tmax_trans = interpolation_T(Tmin), interpolation_T(Tmax)
            try:
                v_low = self.calculate(T=Tmin, method=method)
                if interpolation_property is not None:
                    v_low = interpolation_property(v_low)
                d_low = self._calculate_derivative_transformed(T=Tmin, method=method, order=1)
            except:
                v_low, d_low = None, None
            try:
                v_high = self.calculate(T=Tmax, method=method)
                if interpolation_property is not None:
                    v_high = interpolation_property(v_high)
                d_high = self._calculate_derivative_transformed(T=Tmax, method=method, order=1)
            except:
                v_high, d_high = None, None
            coefficients = [v_low, d_low, v_high, d_high]
        elif extrapolation == 'constant':
            Tmin, Tmax = T_limits[method]
            try:
                v_low = self.calculate(T=Tmin, method=method)
            except:
                v_low = None
            try:
                v_high = self.calculate(T=Tmax, method=method)
            except:
                v_high = None
            coefficients = [v_low, v_high]
        elif extrapolation == 'AntoineAB':
            Tmin, Tmax = T_limits[method]
            try:
                v_low = self.calculate(T=Tmin, method=method)
                d_low = self.calculate_derivative(T=Tmin, method=method, order=1)
                AB_low = Antoine_AB_coeffs_from_point(T=Tmin, Psat=v_low, dPsat_dT=d_low, base=e)
            except:
                AB_low = None
            try:
                v_high = self.calculate(T=Tmax, method=method)
                d_high = self.calculate_derivative(T=Tmax, method=method, order=1)
                AB_high = Antoine_AB_coeffs_from_point(T=Tmax, Psat=v_high, dPsat_dT=d_high, base=e)
            except:
                AB_high = None
            coefficients = [AB_low, AB_high]
        elif extrapolation == 'DIPPR101_ABC':
            Tmin, Tmax = T_limits[method]
            try:
                v_low = self.calculate(T=Tmin, method=method)
                d0_low = self.calculate_derivative(T=Tmin, method=method, order=1)
                d1_low = self.calculate_derivative(T=Tmin, method=method, order=2)
                DIPPR101_ABC_low = DIPPR101_ABC_coeffs_from_point(Tmin, v_low, d0_low, d1_low)
            except:
                DIPPR101_ABC_low = None
            try:
                v_high = self.calculate(T=Tmax, method=method)
                d0_high = self.calculate_derivative(T=Tmax, method=method, order=1)
                d1_high = self.calculate_derivative(T=Tmax, method=method, order=2)
                DIPPR101_ABC_high = DIPPR101_ABC_coeffs_from_point(Tmax, v_high, d0_high, d1_high)
            except:
                DIPPR101_ABC_high = None
            coefficients = [DIPPR101_ABC_low, DIPPR101_ABC_high]
        elif extrapolation == 'Watson':
            Tmin, Tmax = T_limits[method]
            delta = (Tmax-Tmin)*1e-4
            try:
                v0_low = self.calculate(T=Tmin, method=method)
                v1_low = self.calculate(T=Tmin+delta, method=method)
                n_low = Watson_n(Tmin, Tmin+delta, v0_low, v1_low, self.Tc)
            except:
                v0_low, v1_low, n_low = None, None, None
            try:
                v0_high = self.calculate(T=Tmax, method=method)
                v1_high = self.calculate(T=Tmax-delta, method=method)
                n_high = Watson_n(Tmax, Tmax-delta, v0_high, v1_high, self.Tc)
            except:
                v0_high, v1_high, n_high = None, None, None
            coefficients = [v0_low, n_low, v0_high, n_high]
        elif extrapolation == 'interp1d':
            from scipy.interpolate import interp1d
            interpolation_T = self.interpolation_T
            interpolation_property = self.interpolation_property
            interpolation_property_inv = self.interpolation_property_inv
            Tmin, Tmax = T_limits[method]
            if method in self.tabular_data:
                Ts, properties = self.tabular_data[method]
            else:
                Ts = linspace(Tmin, Tmax, self.tabular_extrapolation_pts)
                properties = [self.calculate(T, method=method) for T in Ts]

            if interpolation_T is not None:  # Transform ths Ts with interpolation_T if set
                Ts_interp = [interpolation_T(T) for T in Ts]
            else:
                Ts_interp = Ts
            if interpolation_property is not None:  # Transform ths props with interpolation_property if set
                properties_interp = [interpolation_property(p) for p in properties]
            else:
                properties_interp = properties
            # Only allow linear extrapolation, but with whatever transforms are specified
            extrapolator = interp1d(Ts_interp, properties_interp, fill_value='extrapolate', kind=self.interp1d_extrapolate_kind)
            coefficients = extrapolator
        elif extrapolation is None or extrapolation == 'None':
            coefficients = None
        else:
            raise ValueError("Could not recognize extrapolation setting")
        return coefficients

    @property
    def extrapolation(self):
        '''The string setting of the current extrapolation settings.
        This can be set to a new value to change which extrapolation setting
        is used.
        '''
        return self._extrapolation

    @extrapolation.setter
    def extrapolation(self, extrapolation):
        self._extrapolation = extrapolation
        if extrapolation is None:
            self.extrapolation_split = False
            self._extrapolation_low = self._extrapolation_high = self.extrapolations = None
            return
        self.extrapolation_split = '|' in extrapolation
        if not self.extrapolation_split:
            extrapolations = [extrapolation]
            self._extrapolation_low = self._extrapolation_high = extrapolation
        else:
            extrapolations = extrapolation.split('|')
            if len(extrapolations) != 2:
                raise ValueError("Must have only two extrapolation methods")
            self._extrapolation_low, self._extrapolation_high = extrapolations
            if extrapolations[0] == extrapolations[1]:
                extrapolations.pop()
        self.extrapolations = extrapolations

    def extrapolate(self, T, method, in_range='error'):
        r'''Method to perform extrapolation on a given method according to the
        :obj:`extrapolation` setting.

        Parameters
        ----------
        T : float
            Temperature at which to extrapolate the property, [K]
        method : str
            The method to use, [-]
        in_range : str
            How to handle inputs which are not outside the temperature limits;
            set to 'low' to use the low T extrapolation, 'high' to use the
            high T extrapolation, and 'error' or anything else to raise an
            error in those cases, [-]

        Returns
        -------
        prop : float
            Calculated property, [`units`]
        '''
        T_limits = self.T_limits
        if T < 0.0:
            raise ValueError("Negative temperature")
        T_low, T_high = T_limits[method]
        if T <= T_low or in_range == 'low':
            low = True
            extrapolation = self._extrapolation_low
        elif T >= T_high or in_range == 'high':
            low = False
            extrapolation = self._extrapolation_high
        else:
            raise ValueError("Not outside normal range")
        key = (extrapolation, method)
        extrapolation_coeffs = self.extrapolation_coeffs
        if key in extrapolation_coeffs:
            coeffs = extrapolation_coeffs[key]
        else:
            extrapolation_coeffs[key] = coeffs = self._get_extrapolation_coeffs(extrapolation, method)
            
        if extrapolation == 'linear':
            v_low, d_low, v_high, d_high = coeffs
            interpolation_T = self.interpolation_T
            interpolation_property_inv = self.interpolation_property_inv
            if interpolation_T is not None:
                T_low, T_high = interpolation_T(T_low), interpolation_T(T_high)
                T = interpolation_T(T)
            if low:
                if v_low is None:
                    raise ValueError("Could not extrapolate - model failed to calculate at minimum temperature")
                val = v_low + d_low*(T - T_low)
                if interpolation_property_inv is not None:
                    val = interpolation_property_inv(val)
                return val
            else:
                if v_high is None:
                    raise ValueError("Could not extrapolate - model failed to calculate at maximum temperature")
                val = v_high + d_high*(T - T_high)
                if interpolation_property_inv is not None:
                    val = interpolation_property_inv(val)
                return val
        elif extrapolation == 'constant':
            v_low, v_high = coeffs
            if low:
                if v_low is None:
                    raise ValueError("Could not extrapolate - model failed to calculate at minimum temperature")
                return v_low
            else:
                if v_high is None:
                    raise ValueError("Could not extrapolate - model failed to calculate at maximum temperature")
                return v_high

        elif extrapolation == 'AntoineAB':
            T_low, T_high = T_limits[method]
            AB_low, AB_high = coeffs
            if low:
                if AB_low is None:
                    raise ValueError("Could not extrapolate - model failed to calculate at minimum temperature")
                return Antoine(T, A=AB_low[0], B=AB_low[1], C=0.0, base=e)
            else:
                if AB_high is None:
                    raise ValueError("Could not extrapolate - model failed to calculate at maximum temperature")
                return Antoine(T, A=AB_high[0], B=AB_high[1], C=0.0, base=e)
        elif extrapolation == 'DIPPR101_ABC':
            T_low, T_high = T_limits[method]
            DIPPR101_ABC_low, DIPPR101_ABC_high = coeffs
            if low:
                if DIPPR101_ABC_low is None:
                    raise ValueError("Could not extrapolate - model failed to calculate at minimum temperature")
                return EQ101(T, DIPPR101_ABC_low[0], DIPPR101_ABC_low[1], DIPPR101_ABC_low[2], 0.0, 0.0)
            else:
                if DIPPR101_ABC_high is None:
                    raise ValueError("Could not extrapolate - model failed to calculate at maximum temperature")
                return EQ101(T, DIPPR101_ABC_high[0], DIPPR101_ABC_high[1], DIPPR101_ABC_high[2], 0.0, 0.0)
        elif extrapolation == 'Watson':
            T_low, T_high = T_limits[method]
            v0_low, n_low, v0_high, n_high = coeffs
            if low:
                if v0_low is None:
                    raise ValueError("Could not extrapolate - model failed to calculate at minimum temperature")
                return Watson(T, Hvap_ref=v0_low, T_ref=T_low, Tc=self.Tc, exponent=n_low)
            else:
                if v0_high is None:
                    raise ValueError("Could not extrapolate - model failed to calculate at maximum temperature")
                return Watson(T, Hvap_ref=v0_high, T_ref=T_high, Tc=self.Tc, exponent=n_high)
        elif extrapolation == 'interp1d':
            T_low, T_high = T_limits[method]
            extrapolator = coeffs
            interpolation_T = self.interpolation_T
            if interpolation_T is not None:
                T = interpolation_T(T)
            prop = extrapolator(T)
            if self.interpolation_property is not None:
                prop = self.interpolation_property_inv(prop)
        return float(prop)

    def __init__(self, extrapolation, **kwargs):
        self.local_methods = {}
        """local_methods, dict[str, LocalMethod]: Local methods added by the user."""
        self.extrapolation_coeffs = {}
        """extrapolation_coeffs, dict[tuple[str, str], object]: Cached 
        coefficients and methods used for extrapolation."""
        self.Tmin = None
        '''Minimum temperature at which no method can calculate the
        property under.'''
        self.Tmax = None
        '''Maximum temperature at which no method can calculate the
        property above.'''
        self.tabular_data = {}
        '''tabular_data, dict: Stored (Ts, properties) for any
        tabular data; indexed by provided or autogenerated name.'''
        self.tabular_data_interpolators = {}
        '''tabular_data_interpolators, dict: Stored (extrapolator,
        spline) tuples which are interp1d instances for each set of tabular
        data; indexed by tuple of (name, interpolation_T,
        interpolation_property, interpolation_property_inv) to ensure that
        if an interpolation transform is altered, the old interpolator which
        had been created is no longer used.'''
        self.all_methods = set()
        '''Set of all methods available for a given CASRN and properties;
        filled by :obj:`load_all_methods`.'''
        self.load_all_methods(kwargs.get('load_data', True))

        self.extrapolation = extrapolation

        if kwargs.get('tabular_data', None):
            for name, (Ts, properties) in kwargs['tabular_data'].items():
                self.add_tabular_data(Ts, properties, name=name, check_properties=False)

        self.correlations = {}
        for correlation_name in self.correlation_models.keys():
            # Should be lazy created?
            correlation_key = self.correlation_parameters[correlation_name]
#            setattr(self, correlation_key, {})

            if correlation_key in kwargs:
                for corr_i, corr_kwargs in kwargs[correlation_key].items():
                    self.add_correlation(name=corr_i, model=correlation_name,
                                         **corr_kwargs)

        poly_fit = kwargs.get('poly_fit', None)
        method =  kwargs.get('method', getattr(self, '_method', None))
        if poly_fit is not None:
            if self.__class__.__name__ == 'EnthalpyVaporization':
                self.poly_fit_Tc = poly_fit[2]
                self._set_poly_fit((poly_fit[0], poly_fit[1], poly_fit[3]))
            elif self.__class__.__name__ == 'VaporPressure':
                self._set_poly_fit(poly_fit)
                if self.Tmin is None and hasattr(self, 'poly_fit_Tmin'):
                    self.Tmin = self.poly_fit_Tmin*.01
                if self.Tmax is None and hasattr(self, 'poly_fit_Tmax'):
                    self.Tmax = self.poly_fit_Tmax*10.0
            elif self.__class__.__name__ == 'SublimationPressure':
                self._set_poly_fit(poly_fit)
                if self.Tmin is None and hasattr(self, 'poly_fit_Tmin'):
                    self.Tmin = self.poly_fit_Tmin*.001
                if self.Tmax is None and hasattr(self, 'poly_fit_Tmax'):
                    self.Tmax = self.poly_fit_Tmax*10.0
            else:
                self._set_poly_fit(poly_fit)
            method = POLY_FIT
        elif method is None:
            all_methods = self.all_methods
            for i in self.ranked_methods: 
                if i in all_methods:
                    method = i
                    break
        self.method = method

    def load_all_methods(self, load_data):
        pass

    def calculate(self, T, method):
        r'''Method to calculate a property with a specified method, with no
        validity checking or error handling. Demo function for testing only;
        must be implemented according to the methods available for each
        individual method. Include the interpolation call here.

        Parameters
        ----------
        T : float
            Temperature at which to calculate the property, [K]
        method : str
            Method name to use

        Returns
        -------
        prop : float
            Calculated property, [`units`]
        '''
        return self._base_calculate(T, method)

    def test_method_validity(self, T, method):
        r'''Method to test the validity of a specified method for a given
        temperature. Demo function for testing only;
        must be implemented according to the methods available for each
        individual method. Include the interpolation check here.

        Parameters
        ----------
        T : float
            Temperature at which to determine the validity of the method, [K]
        method : str
            Method name to use

        Returns
        -------
        validity : bool
            Whether or not a specifid method is valid
        '''
        T_limits = self.T_limits
        if method in T_limits:
            Tmin, Tmax = T_limits[method]
            validity = Tmin <= T <= Tmax
        elif method == POLY_FIT:
            validity = True
        elif method in self.tabular_data:
            if self.tabular_extrapolation_permitted:
                validity = True
            else:
                Ts, properties = self.tabular_data[method]
                validity = Ts[0] < T < Ts[-1]
        else:
            raise ValueError("method '%s' not valid" %method)
        return validity
