#!/usr/bin/env python3
"""Generate the original public EvoLDO-Bench development set.

The task definitions below are independently authored. This generator is deterministic so changes to
public task assets are reviewable. Public development oracles are deliberately stored outside each
task directory; a sealed exam must use an external private oracle store instead.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
TASKS_ROOT = ROOT / "benchmarks" / "ldo_original" / "dev" / "tasks"
ORACLE_ROOT = ROOT / "benchmarks" / "ldo_original" / "dev_reference" / "oracles"
REGISTRY = ROOT / "benchmarks" / "ldo_original" / "registry.jsonl"


def jd(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def variant(name: str, scenario: Dict[str, Any], expected: Dict[str, Any]) -> Dict[str, Any]:
    return {"name": name, "scenario": scenario, "expected": expected}


def expected(conclusion: str, regime: str, held: List[str], facts: List[str], mechanisms: List[str], actions: List[str], forbidden: List[str]) -> Dict[str, Any]:
    return {
        "conclusion": conclusion,
        "analysis_regime": regime,
        "held_fixed": held,
        "evidence_facts": facts,
        "mechanism_tags": mechanisms,
        "recommended_actions": actions,
        "forbidden_actions": forbidden,
    }


FAMILIES: List[Dict[str, Any]] = [
    {
        "family_id": "structure_feedback_sign",
        "suite": "structure",
        "level": "L1",
        "capabilities": ["structure", "feedback_stability"],
        "title": "Determine the LDO loop sign from device polarity and error-amplifier action",
        "variants": [
            variant(
                "canonical",
                {
                    "question": "Classify the small-signal loop sign.",
                    "pass_device": {"type": "PMOS", "drain": "VOUT", "gate": "VCTRL", "source": "VIN", "body": "VIN"},
                    "error_amplifier_action": "When VOUT falls below target, VCTRL decreases.",
                    "changed_from_canonical": "none",
                },
                expected("negative_feedback", "small_signal", ["pmos_polarity", "error_amplifier_gain_sign", "supply_and_load"], ["pmos_gate_falls_when_output_is_low", "pass_current_increases_when_pmos_gate_falls"], ["loop_restores_output", "pmos_gate_to_current_inverting"], ["verify_loop_gain_with_correct_break_point"], ["infer_stability_margin_without_stb", "reverse_device_polarity"]),
            ),
            variant(
                "metamorphic",
                {
                    "question": "Classify the small-signal loop sign after net and instance renaming.",
                    "pass_device": {"type": "PMOS", "drain": "N_REG", "gate": "N_EA", "source": "N_SUP", "body": "N_SUP"},
                    "error_amplifier_action": "When N_REG falls below target, N_EA decreases.",
                    "metamorphic_transform": "VOUT->N_REG, VCTRL->N_EA, VIN->N_SUP; instance order shuffled",
                    "changed_from_canonical": "names only",
                },
                expected("negative_feedback", "small_signal", ["pmos_polarity", "error_amplifier_gain_sign", "supply_and_load"], ["pmos_gate_falls_when_output_is_low", "pass_current_increases_when_pmos_gate_falls"], ["loop_restores_output", "pmos_gate_to_current_inverting"], ["verify_loop_gain_with_correct_break_point"], ["infer_stability_margin_without_stb", "treat_renaming_as_topology_change"]),
            ),
            variant(
                "counterexample",
                {
                    "question": "Classify the small-signal loop sign after one amplifier output polarity is reversed.",
                    "pass_device": {"type": "PMOS", "drain": "VOUT", "gate": "VCTRL", "source": "VIN", "body": "VIN"},
                    "error_amplifier_action": "When VOUT falls below target, VCTRL increases.",
                    "changed_from_canonical": "only error-amplifier output polarity is reversed",
                },
                expected("positive_feedback", "small_signal", ["pmos_polarity", "error_amplifier_gain_sign", "supply_and_load"], ["pmos_gate_rises_when_output_is_low", "pass_current_decreases_when_pmos_gate_rises"], ["loop_amplifies_output_error", "pmos_gate_to_current_inverting"], ["correct_error_amplifier_polarity_before_compensation"], ["tune_compensation_before_fixing_sign", "accept_positive_feedback"]),
            ),
        ],
    },
    {
        "family_id": "structure_pass_body",
        "suite": "structure",
        "level": "L1",
        "capabilities": ["structure", "operating_point"],
        "title": "Check high-side PMOS pass-device body connectivity",
        "variants": [
            variant("canonical", {"pass_device": {"type": "PMOS", "d": "VOUT", "g": "VG", "s": "VIN", "b": "VIN"}, "vin_range_v": [0.9, 1.2], "vout_target_v": 0.8, "changed_from_canonical": "none"}, expected("pmos_high_side_body_valid", "dc_operating_point", ["device_flavor", "vin_range", "load_current"], ["body_tied_to_highest_local_potential", "source_is_input_supply"], ["body_diode_reverse_biased", "body_effect_minimized"], ["verify_vds_vgs_vbs_across_corners"], ["short_body_to_output", "ignore_body_connection"])),
            variant("metamorphic", {"pass_device": {"type": "PMOS", "d": "N2", "g": "N3", "s": "N1", "b": "N1"}, "net_aliases": {"N1": "input rail", "N2": "regulated output"}, "vin_range_v": [0.9, 1.2], "vout_target_v": 0.8, "changed_from_canonical": "node aliases and MOS terminal presentation only"}, expected("pmos_high_side_body_valid", "dc_operating_point", ["device_flavor", "vin_range", "load_current"], ["body_tied_to_highest_local_potential", "source_is_input_supply"], ["body_diode_reverse_biased", "body_effect_minimized"], ["verify_vds_vgs_vbs_across_corners"], ["treat_renaming_as_topology_change", "ignore_body_connection"])),
            variant("counterexample", {"pass_device": {"type": "PMOS", "d": "VOUT", "g": "VG", "s": "VIN", "b": "VOUT"}, "vin_range_v": [0.9, 1.2], "vout_target_v": 0.8, "changed_from_canonical": "only body moves from VIN to VOUT"}, expected("pmos_body_misconnected_risk", "dc_operating_point", ["device_flavor", "vin_range", "load_current"], ["body_not_tied_to_highest_local_potential", "body_source_voltage_nonzero"], ["body_effect_increases_threshold", "junction_risk_requires_pdk_check"], ["retie_body_to_valid_high_potential", "rerun_operating_region_audit"], ["compensate_body_error_with_nodeset", "ignore_body_connection"])),
        ],
    },
    {
        "family_id": "structure_floating_bias",
        "suite": "structure",
        "level": "L1",
        "capabilities": ["structure", "diagnosis"],
        "title": "Detect a floating cascode bias node",
        "variants": [
            variant("canonical", {"cascode_gate": "VBC", "drivers": [{"instance": "M_DIODE", "connection": "diode_connected_bias_generator"}], "loads": ["M_CASC_N", "M_CASC_P"], "changed_from_canonical": "none"}, expected("bias_path_complete", "connectivity", ["hierarchy_flattening", "global_net_rules", "pin_directions"], ["cascode_gate_has_dc_driver", "bias_generator_is_supply_referenced"], ["gate_has_defined_dc_path", "cascode_operating_point_can_be_tested"], ["verify_bias_voltage_and_device_saturation"], ["declare_node_floating_without_hierarchy_check", "add_nodeset_as_connectivity_fix"])),
            variant("metamorphic", {"cascode_gate": "N_B7", "drivers": [{"instance": "XI_BIAS/M4", "connection": "diode_connected_bias_generator"}], "loads": ["XI_EA/M8", "XI_EA/M9"], "transform": "hierarchical names introduced", "changed_from_canonical": "hierarchy and names only"}, expected("bias_path_complete", "connectivity", ["hierarchy_flattening", "global_net_rules", "pin_directions"], ["cascode_gate_has_dc_driver", "bias_generator_is_supply_referenced"], ["gate_has_defined_dc_path", "cascode_operating_point_can_be_tested"], ["verify_bias_voltage_and_device_saturation"], ["treat_hierarchy_as_disconnection", "add_nodeset_as_connectivity_fix"])),
            variant("counterexample", {"cascode_gate": "VB_FLOAT", "drivers": [], "loads": ["M_CASC_N", "M_CASC_P"], "changed_from_canonical": "only the bias generator connection is removed"}, expected("floating_bias_node", "connectivity", ["hierarchy_flattening", "global_net_rules", "pin_directions"], ["cascode_gate_has_no_dc_driver", "node_only_connects_to_mos_gates"], ["gate_charge_has_no_defined_dc_path", "operating_point_is_not_physical"], ["restore_a_dc_bias_path", "rerun_connectivity_before_simulation"], ["use_nodeset_as_permanent_fix", "tune_device_widths_first"])),
        ],
    },
    {
        "family_id": "trend_compensation_cap",
        "suite": "trend",
        "level": "L2",
        "capabilities": ["feedback_stability", "transient"],
        "title": "Interpret a controlled three-point compensation-capacitor sweep",
        "variants": [
            variant("canonical", {"sweep": [{"cc_pf": 0.5, "phase_margin_deg": 37, "ugf_mhz": 15.1, "settling_us": 1.2}, {"cc_pf": 1.0, "phase_margin_deg": 56, "ugf_mhz": 9.4, "settling_us": 1.7}, {"cc_pf": 2.0, "phase_margin_deg": 69, "ugf_mhz": 5.2, "settling_us": 2.9}], "held_fixed": ["bias_current", "load_current", "pass_size", "output_capacitance"], "changed_from_canonical": "none"}, expected("stability_improves_bandwidth_falls", "small_signal_and_transient", ["bias_current", "load_current", "pass_size", "output_capacitance"], ["phase_margin_rises_across_three_points", "ugf_falls_across_three_points", "settling_time_increases"], ["dominant_pole_moves_lower", "bandwidth_stability_tradeoff"], ["select_smallest_cc_with_required_margin", "verify_load_corners"], ["maximize_cc_without_transient_check", "claim_startup_is_proven_by_phase_margin"])),
            variant("metamorphic", {"sweep": [{"c_comp_f": 5e-13, "pm_deg": 37, "unity_hz": 15100000, "t_settle_s": 1.2e-6}, {"c_comp_f": 1e-12, "pm_deg": 56, "unity_hz": 9400000, "t_settle_s": 1.7e-6}, {"c_comp_f": 2e-12, "pm_deg": 69, "unity_hz": 5200000, "t_settle_s": 2.9e-6}], "held_fixed": ["bias_current", "load_current", "pass_size", "output_capacitance"], "transform": "SI units and column names changed", "changed_from_canonical": "representation only"}, expected("stability_improves_bandwidth_falls", "small_signal_and_transient", ["bias_current", "load_current", "pass_size", "output_capacitance"], ["phase_margin_rises_across_three_points", "ugf_falls_across_three_points", "settling_time_increases"], ["dominant_pole_moves_lower", "bandwidth_stability_tradeoff"], ["select_smallest_cc_with_required_margin", "verify_load_corners"], ["treat_unit_conversion_as_new_physics", "claim_startup_is_proven_by_phase_margin"])),
            variant("counterexample", {"sweep": [{"cc_pf": 0.5, "load_ma": 1, "phase_margin_deg": 37, "ugf_mhz": 15.1}, {"cc_pf": 1.0, "load_ma": 20, "phase_margin_deg": 56, "ugf_mhz": 9.4}, {"cc_pf": 2.0, "load_ma": 100, "phase_margin_deg": 69, "ugf_mhz": 5.2}], "held_fixed": ["bias_current", "pass_size", "output_capacitance"], "changed_from_canonical": "load current now changes with Cc"}, expected("trend_not_identifiable", "small_signal", ["bias_current", "pass_size", "output_capacitance"], ["cc_and_load_change_together", "phase_margin_change_is_confounded"], ["held_fixed_violation", "causal_attribution_not_supported"], ["rerun_cc_sweep_at_fixed_load", "separate_load_and_cc_interventions"], ["attribute_all_change_to_cc", "publish_confounded_trend"])),
        ],
    },
    {
        "family_id": "trend_pass_size_turning",
        "suite": "trend",
        "level": "L2",
        "capabilities": ["operating_point", "feedback_stability", "transient"],
        "title": "Recognize pass-device sizing tradeoffs and a stability turning point",
        "variants": [
            variant("canonical", {"sweep": [{"pass_scale": 1, "dropout_mv": 182, "phase_margin_deg": 71, "overshoot_mv": 13}, {"pass_scale": 2, "dropout_mv": 116, "phase_margin_deg": 58, "overshoot_mv": 29}, {"pass_scale": 4, "dropout_mv": 87, "phase_margin_deg": 32, "overshoot_mv": 78}], "held_fixed": ["driver_size", "bias_current", "compensation", "load_step"], "changed_from_canonical": "none"}, expected("dropout_improves_stability_degrades", "dc_small_signal_transient", ["driver_size", "bias_current", "compensation", "load_step"], ["dropout_decreases_with_pass_scale", "phase_margin_decreases_with_pass_scale", "overshoot_increases"], ["pass_rds_on_decreases", "pass_gate_capacitance_loads_driver"], ["co_optimize_driver_and_compensation", "stop_before_phase_margin_gate"], ["maximize_pass_size_only", "ignore_gate_drive_pole"])),
            variant("metamorphic", {"sweep": [{"nf_normalized": 1, "vin_minus_vout_v": 0.182, "pm_deg": 71, "peak_error_v": 0.013}, {"nf_normalized": 2, "vin_minus_vout_v": 0.116, "pm_deg": 58, "peak_error_v": 0.029}, {"nf_normalized": 4, "vin_minus_vout_v": 0.087, "pm_deg": 32, "peak_error_v": 0.078}], "held_fixed": ["driver_size", "bias_current", "compensation", "load_step"], "changed_from_canonical": "units and parameter label only"}, expected("dropout_improves_stability_degrades", "dc_small_signal_transient", ["driver_size", "bias_current", "compensation", "load_step"], ["dropout_decreases_with_pass_scale", "phase_margin_decreases_with_pass_scale", "overshoot_increases"], ["pass_rds_on_decreases", "pass_gate_capacitance_loads_driver"], ["co_optimize_driver_and_compensation", "stop_before_phase_margin_gate"], ["treat_unit_conversion_as_new_physics", "ignore_gate_drive_pole"])),
            variant("counterexample", {"sweep": [{"pass_scale": 1, "driver_scale": 1, "dropout_mv": 182, "phase_margin_deg": 71}, {"pass_scale": 2, "driver_scale": 2, "dropout_mv": 116, "phase_margin_deg": 70}, {"pass_scale": 4, "driver_scale": 4, "dropout_mv": 87, "phase_margin_deg": 68}], "held_fixed": ["driver_to_pass_ratio", "bias_density", "compensation", "load_step"], "changed_from_canonical": "driver strength now scales with pass size"}, expected("dropout_improves_without_major_stability_loss", "dc_and_small_signal", ["driver_to_pass_ratio", "bias_density", "compensation", "load_step"], ["dropout_decreases_with_pass_scale", "phase_margin_remains_nearly_constant"], ["driver_tracks_gate_capacitance", "pass_rds_on_decreases"], ["verify_iq_area_and_transient_cost", "check_all_load_corners"], ["reuse_canonical_stability_conclusion", "ignore_driver_iq_cost"])),
        ],
    },
    {
        "family_id": "trend_divider_current",
        "suite": "trend",
        "level": "L2",
        "capabilities": ["noise", "operating_point", "sizing"],
        "title": "Explain feedback-divider current tradeoffs",
        "variants": [
            variant("canonical", {"sweep": [{"divider_ua": 1, "iq_ua": 18, "divider_noise_uvrms": 42, "dc_error_mv": 7.0}, {"divider_ua": 5, "iq_ua": 22, "divider_noise_uvrms": 19, "dc_error_mv": 2.0}, {"divider_ua": 20, "iq_ua": 37, "divider_noise_uvrms": 9, "dc_error_mv": 0.8}], "held_fixed": ["error_amplifier", "reference", "load", "resistor_ratio"], "changed_from_canonical": "none"}, expected("accuracy_noise_improve_iq_cost", "dc_and_noise", ["error_amplifier", "reference", "load", "resistor_ratio"], ["dc_error_decreases", "divider_noise_decreases", "iq_increases"], ["divider_impedance_falls", "thermal_noise_and_bias_loading_tradeoff"], ["choose_current_from_noise_accuracy_budget", "include_divider_in_iq"], ["maximize_divider_current_unconditionally", "exclude_divider_from_iq"])),
            variant("metamorphic", {"sweep": [{"r_total_kohm": 800, "supply_current_ua": 18, "noise_uvrms": 42, "error_mv": 7.0}, {"r_total_kohm": 160, "supply_current_ua": 22, "noise_uvrms": 19, "error_mv": 2.0}, {"r_total_kohm": 40, "supply_current_ua": 37, "noise_uvrms": 9, "error_mv": 0.8}], "vout_v": 0.8, "held_fixed": ["error_amplifier", "reference", "load", "resistor_ratio"], "transform": "divider current represented by total resistance", "changed_from_canonical": "representation only"}, expected("accuracy_noise_improve_iq_cost", "dc_and_noise", ["error_amplifier", "reference", "load", "resistor_ratio"], ["dc_error_decreases", "divider_noise_decreases", "iq_increases"], ["divider_impedance_falls", "thermal_noise_and_bias_loading_tradeoff"], ["choose_current_from_noise_accuracy_budget", "include_divider_in_iq"], ["treat_inverse_resistance_as_opposite_trend", "exclude_divider_from_iq"])),
            variant("counterexample", {"sweep": [{"divider_ua": 1, "iq_ua": 18, "divider_noise_uvrms": 42, "dc_error_mv": 0.4}, {"divider_ua": 5, "iq_ua": 22, "divider_noise_uvrms": 19, "dc_error_mv": 0.4}, {"divider_ua": 20, "iq_ua": 37, "divider_noise_uvrms": 9, "dc_error_mv": 0.4}], "feedback_buffer": "idealized high-input-impedance analysis buffer", "held_fixed": ["error_amplifier", "reference", "load", "resistor_ratio", "buffer_offset"], "changed_from_canonical": "feedback input loading is removed"}, expected("noise_improves_iq_cost_accuracy_flat", "dc_and_noise", ["error_amplifier", "reference", "load", "resistor_ratio", "buffer_offset"], ["dc_error_remains_constant", "divider_noise_decreases", "iq_increases"], ["input_loading_removed", "thermal_noise_current_tradeoff_remains"], ["choose_current_from_noise_and_iq_budget", "verify_real_buffer_noise"], ["claim_accuracy_improves_from_supplied_data", "exclude_divider_from_iq"])),
        ],
    },
    {
        "family_id": "diagnosis_infra_vs_circuit",
        "suite": "diagnosis",
        "level": "L2",
        "capabilities": ["diagnosis", "evidence_integrity"],
        "title": "Separate simulator infrastructure failure from circuit failure",
        "variants": [
            variant("canonical", {"log": ["analog simulator startup", "ERROR: required simulator license feature is unavailable", "simulation terminated before netlist elaboration"], "result_files": [], "changed_from_canonical": "none"}, expected("infra_license", "execution_status", ["submitted_netlist", "simulator_binary", "license_feature"], ["simulator_stopped_before_elaboration", "no_operating_point_evidence_exists"], ["license_failure_is_not_circuit_failure", "missing_evidence_blocks_design_claim"], ["obtain_license_or_use_authorized_simulator", "rerun_same_candidate_before_tuning"], ["resize_transistors_from_this_log", "mark_candidate_as_circuit_fail"])),
            variant("metamorphic", {"log": ["license checkout failed for a required simulator feature", "license manager: requested feature unavailable", "analysis dc was not started"], "result_files": [], "changed_from_canonical": "generic log wording only"}, expected("infra_license", "execution_status", ["submitted_netlist", "simulator_binary", "license_feature"], ["simulator_stopped_before_elaboration", "no_operating_point_evidence_exists"], ["license_failure_is_not_circuit_failure", "missing_evidence_blocks_design_claim"], ["obtain_license_or_use_authorized_simulator", "rerun_same_candidate_before_tuning"], ["treat_log_rewording_as_new_failure", "mark_candidate_as_circuit_fail"])),
            variant("counterexample", {"log": ["license checkout succeeded", "netlist elaborated", "dcOp completed successfully", "V(EN)=0.00 V", "V(VOUT)=0.00 V"], "bench_contract": {"enable_active_level": 1, "required_enable_v": 0.8}, "changed_from_canonical": "license succeeds and valid OP evidence shows EN is low"}, expected("bench_stimulus", "dc_operating_point", ["dut_netlist", "pdk_models", "load_condition"], ["simulation_completed", "enable_is_below_active_level"], ["disabled_dut_explains_zero_output", "bench_failure_precedes_sizing"], ["correct_enable_stimulus", "rerun_operating_point_before_tuning"], ["resize_pass_device_first", "mark_license_failure"])),
        ],
    },
    {
        "family_id": "diagnosis_wrong_probe",
        "suite": "diagnosis",
        "level": "L2",
        "capabilities": ["diagnosis", "feedback_stability", "evidence_integrity"],
        "title": "Detect an invalid loop-gain probe",
        "variants": [
            variant("canonical", {"intended_loop_break": "between EA output and PMOS pass gate", "actual_probe": "inserted in VREF source branch", "reported_phase_margin_deg": 92, "loop_gain_dc_db": -18, "changed_from_canonical": "none"}, expected("measurement_probe", "stb", ["dut_topology", "load", "bias", "compensation"], ["probe_is_outside_return_loop", "reported_loop_gain_is_below_unity_at_dc"], ["stb_probe_does_not_measure_intended_loop", "measurement_invalidates_margin_claim"], ["move_probe_to_loop_break", "validate_return_ratio_orientation"], ["accept_phase_margin_number_without_loop_gain", "retune_compensation_first"])),
            variant("metamorphic", {"intended_loop_break": "N_EA_OUT to M_PASS.G", "actual_probe": "between reference pin N_REF and ideal reference source", "reported_phase_margin_deg": 92, "loop_gain_dc_db": -18, "changed_from_canonical": "node names and hierarchy only"}, expected("measurement_probe", "stb", ["dut_topology", "load", "bias", "compensation"], ["probe_is_outside_return_loop", "reported_loop_gain_is_below_unity_at_dc"], ["stb_probe_does_not_measure_intended_loop", "measurement_invalidates_margin_claim"], ["move_probe_to_loop_break", "validate_return_ratio_orientation"], ["treat_renaming_as_valid_probe", "retune_compensation_first"])),
            variant("counterexample", {"intended_loop_break": "between EA output and PMOS pass gate", "actual_probe": "at intended break with correct iprobe orientation", "reported_phase_margin_deg": -12, "loop_gain_dc_db": 64, "unity_crossing_mhz": 8.2, "changed_from_canonical": "probe is corrected; evidence now shows a negative margin"}, expected("circuit_stability", "stb", ["dut_topology", "load", "bias", "compensation"], ["probe_is_in_intended_loop", "negative_phase_margin_at_unity_crossing"], ["valid_stb_evidence_shows_instability", "circuit_requires_loop_repair"], ["inspect_poles_and_compensation", "verify_after_stability_fix"], ["blame_probe_after_it_is_valid", "accept_negative_phase_margin"])),
        ],
    },
    {
        "family_id": "sizing_role_aware_space",
        "suite": "sizing",
        "level": "L3",
        "capabilities": ["sizing", "operating_point", "feedback_stability"],
        "title": "Build a role-aware legal sizing search space",
        "variants": [
            variant("canonical", {"objective": "reduce dropout while preserving PM>=55deg and IQ<=30uA", "roles": {"M_PASS": "pmos_pass", "M_DRV": "pass_gate_driver", "M_IN1,M_IN2": "input_pair", "C_COMP": "compensation"}, "legal_parameters": {"M_PASS": ["nf", "m"], "M_DRV": ["nf", "m"], "M_IN1,M_IN2": ["nf", "m"], "C_COMP": ["cap_code"]}, "baseline_failure": ["dropout_high", "pm_margin_small"], "changed_from_canonical": "none"}, expected("role_aware_search_space", "sizing_configuration", ["topology", "device_flavors", "supply", "load_profile"], ["pass_role_controls_dropout", "driver_and_compensation_control_gate_pole"], ["coupled_parameters_must_be_searched_together", "legal_geometry_only"], ["include_pass_driver_compensation_parameters", "preserve_input_pair_symmetry"], ["search_illegal_width", "vary_one_input_device_only"])),
            variant("metamorphic", {"objective": "reduce dropout while preserving PM>=55deg and IQ<=30uA", "roles": {"MP7": "pmos_pass", "MN9": "pass_gate_driver", "MN1,MN2": "input_pair", "C4": "compensation"}, "legal_parameters": {"MP7": ["nf", "m"], "MN9": ["nf", "m"], "MN1,MN2": ["nf", "m"], "C4": ["cap_code"]}, "baseline_failure": ["dropout_high", "pm_margin_small"], "changed_from_canonical": "instance names only"}, expected("role_aware_search_space", "sizing_configuration", ["topology", "device_flavors", "supply", "load_profile"], ["pass_role_controls_dropout", "driver_and_compensation_control_gate_pole"], ["coupled_parameters_must_be_searched_together", "legal_geometry_only"], ["include_pass_driver_compensation_parameters", "preserve_input_pair_symmetry"], ["treat_names_as_roles", "vary_one_input_device_only"])),
            variant("counterexample", {"objective": "repair all-zero cold start while DC with forced initial condition already regulates", "roles": {"M_PASS": "pmos_pass", "M_START": "startup_injector", "M_KEEP": "startup_keeper", "C_TIMER": "startup_timer"}, "proposed_search": ["M_PASS.nf"], "baseline_failure": ["cold_start_timeout"], "changed_from_canonical": "objective changes from dropout to startup; proposed space still contains pass size only"}, expected("search_space_misses_startup_controls", "sizing_configuration", ["topology", "device_flavors", "supply", "load_profile"], ["forced_initial_condition_proves_regulation_path", "startup_controls_absent_from_search"], ["failure_role_must_drive_parameter_selection", "pass_size_alone_does_not_create_startup_path"], ["include_startup_strength_and_timing", "run_cold_start_shutdown_restart"], ["optimize_pass_size_only", "use_nodeset_as_final_fix"])),
        ],
    },
    {
        "family_id": "migration_planar_to_finfet",
        "suite": "migration",
        "level": "L3",
        "capabilities": ["migration", "operating_point", "evidence_integrity"],
        "title": "Migrate design intent rather than copying planar W/L",
        "variants": [
            variant("canonical", {"source_device": {"role": "input_pair", "w_um": 12.0, "l_um": 0.18, "id_ua": 20, "gm_over_id": 14, "vds_margin_mv": 110}, "target_constraints": {"geometry": "integer_fin", "allowed_lengths_nm": [16, 20, 24], "fin_range": [2, 64]}, "changed_from_canonical": "none"}, expected("migrate_intent_then_resize", "pdk_migration", ["architecture", "branch_current_target", "headroom_budget", "load_spec"], ["target_uses_integer_fin_geometry", "source_has_role_and_operating_point_intent"], ["planar_width_is_not_portable", "gm_id_and_headroom_are_migration_invariants"], ["map_device_flavor_by_role", "restore_operating_point_before_ac"], ["copy_planar_width_literal", "skip_target_pdk_legality"])),
            variant("metamorphic", {"source_device": {"role": "differential_transconductor", "width_m": 1.2e-5, "length_m": 1.8e-7, "drain_current_a": 2e-5, "gm_id_per_v": 14, "vds_margin_v": 0.11}, "target_constraints": {"geometry": "integer_fin", "allowed_lengths_m": [1.6e-8, 2e-8, 2.4e-8], "fin_range": [2, 64]}, "changed_from_canonical": "SI units and role synonym only"}, expected("migrate_intent_then_resize", "pdk_migration", ["architecture", "branch_current_target", "headroom_budget", "load_spec"], ["target_uses_integer_fin_geometry", "source_has_role_and_operating_point_intent"], ["planar_width_is_not_portable", "gm_id_and_headroom_are_migration_invariants"], ["map_device_flavor_by_role", "restore_operating_point_before_ac"], ["treat_unit_conversion_as_new_design", "skip_target_pdk_legality"])),
            variant("counterexample", {"source_device": {"role": "input_pair", "w_um": 12.0, "l_um": 0.18}, "proposed_target_device": {"w_um": 12.0, "l_um": 0.18, "fins": 12.5}, "target_constraints": {"geometry": "integer_fin", "allowed_lengths_nm": [16, 20, 24], "fin_range": [2, 64]}, "changed_from_canonical": "proposal copies W/L and creates fractional fins"}, expected("illegal_geometry_and_intent_loss", "pdk_migration", ["architecture", "branch_current_target", "headroom_budget", "load_spec"], ["fractional_fin_is_illegal", "copied_length_is_not_in_target_set"], ["literal_geometry_copy_loses_operating_point_intent", "pdk_legality_gate_fails"], ["reject_candidate_before_simulation", "resurvey_legal_device_parameters"], ["round_silently_without_requalification", "accept_illegal_geometry"])),
        ],
    },
    {
        "family_id": "system_noise_sensitivity",
        "suite": "system_impact",
        "level": "L2",
        "capabilities": ["system_impact", "noise"],
        "title": "Map LDO output noise through a downstream sensitivity",
        "variants": [
            variant("canonical", {"ldo_output_noise_uvrms": 200, "downstream_sensitivity_v_per_v": 0.4, "bandwidth_and_units_already_matched": True, "changed_from_canonical": "none"}, expected("system_error_scales_with_sensitivity", "noise_propagation", ["integration_bandwidth", "uncorrelated_other_noise", "downstream_operating_point"], ["ldo_noise_is_200uvrms", "downstream_sensitivity_is_0p4"], ["small_signal_noise_scales_by_absolute_sensitivity", "rms_units_are_preserved"], ["report_80uvrms_output_error", "verify_sensitivity_across_operating_range"], ["add_uncorrelated_noise_linearly", "ignore_bandwidth_alignment"])),
            variant("metamorphic", {"ldo_output_noise_vrms": 0.0002, "downstream_gain_v_per_v": -0.4, "bandwidth_and_units_already_matched": True, "changed_from_canonical": "SI units and negative sensitivity sign"}, expected("system_error_scales_with_sensitivity", "noise_propagation", ["integration_bandwidth", "uncorrelated_other_noise", "downstream_operating_point"], ["ldo_noise_is_200uvrms", "downstream_sensitivity_magnitude_is_0p4"], ["small_signal_noise_scales_by_absolute_sensitivity", "rms_sign_is_not_negative"], ["report_80uvrms_output_error", "verify_sensitivity_across_operating_range"], ["report_negative_rms_noise", "ignore_bandwidth_alignment"])),
            variant("counterexample", {"ldo_output_noise_uvrms": 200, "downstream_sensitivity_v_per_v": 1.2, "bandwidth_and_units_already_matched": True, "changed_from_canonical": "only downstream sensitivity changes from 0.4 to 1.2"}, expected("system_error_scales_with_sensitivity", "noise_propagation", ["integration_bandwidth", "uncorrelated_other_noise", "downstream_operating_point"], ["ldo_noise_is_200uvrms", "downstream_sensitivity_is_1p2"], ["small_signal_noise_scales_by_absolute_sensitivity", "sensitivity_above_one_amplifies_noise"], ["report_240uvrms_output_error", "consider_lower_noise_ldo_or_lower_sensitivity"], ["reuse_80uvrms_result", "ignore_sensitivity_change"])),
        ],
    },
    {
        "family_id": "design_closure_cold_start",
        "suite": "design_closure",
        "level": "L3",
        "capabilities": ["startup_enable", "diagnosis", "evidence_integrity"],
        "title": "Choose the next action for a cold-start failure without ideal fixes",
        "variants": [
            variant("canonical", {"evidence": {"dc_op_with_forced_initial_condition": "VOUT regulates", "cold_start_from_all_zero": "timeout at VOUT=0", "enable": "valid high", "license": "ok", "startup_injector": "absent"}, "rules": ["no nodeset or forced IC in final DUT", "no ideal bias sources in final DUT"], "changed_from_canonical": "none"}, expected("startup_path_missing", "startup_transient", ["dut_topology", "pdk", "supply_ramp", "load"], ["forced_initial_condition_reaches_regulation", "all_zero_cold_start_fails", "enable_is_valid"], ["regulation_loop_exists_but_zero_state_is_trapping", "startup_requires_physical_escape_path"], ["add_self_timed_startup", "verify_shutdown_restart", "rerun_full_qualification"], ["use_nodeset_as_final_fix", "add_ideal_current_source"])),
            variant("metamorphic", {"evidence": {"dc_op_seeded": "N_REG reaches target", "power_up_unseeded": "N_REG remains zero", "ENB": "valid active-low", "simulator_checkout": "ok", "kick_branch": "not present"}, "rules": ["no nodeset or forced IC in final DUT", "no ideal bias sources in final DUT"], "changed_from_canonical": "signal names and active-low enable representation only"}, expected("startup_path_missing", "startup_transient", ["dut_topology", "pdk", "supply_ramp", "load"], ["forced_initial_condition_reaches_regulation", "all_zero_cold_start_fails", "enable_is_valid"], ["regulation_loop_exists_but_zero_state_is_trapping", "startup_requires_physical_escape_path"], ["add_self_timed_startup", "verify_shutdown_restart", "rerun_full_qualification"], ["treat_active_low_name_as_disabled", "add_ideal_current_source"])),
            variant("counterexample", {"evidence": {"dc_op_with_forced_initial_condition": "not run", "cold_start_from_all_zero": "not run", "enable": "unknown", "license": "checkout failed before netlist elaboration", "startup_injector": "unknown"}, "rules": ["no nodeset or forced IC in final DUT", "no ideal bias sources in final DUT"], "changed_from_canonical": "simulation never starts because the license is unavailable"}, expected("infra_license", "execution_status", ["submitted_netlist", "simulator_binary", "license_feature"], ["simulation_did_not_start", "startup_evidence_is_absent"], ["license_failure_prevents_circuit_diagnosis", "missing_evidence_blocks_startup_claim"], ["restore_authorized_simulation", "rerun_unchanged_candidate"], ["add_startup_transistors_without_evidence", "mark_circuit_as_startup_fail"])),
        ],
    },
]

# Add an original netlist snippet to structure tasks. It is evidence only, not simulator-ready PDK IP.
NETLISTS = {
    "structure_feedback_sign": {
        "canonical": "* Original conceptual LDO structure\nM_PASS VOUT VCTRL VIN VIN PMOS\n* EA action is specified in case.json\n",
        "metamorphic": "* Same graph after renaming\nM7 N_REG N_EA N_SUP N_SUP PMOS\n* EA action is specified in case.json\n",
        "counterexample": "* Same PMOS pass graph; EA polarity differs in case.json\nM_PASS VOUT VCTRL VIN VIN PMOS\n",
    },
    "structure_pass_body": {
        "canonical": "M_PASS VOUT VG VIN VIN PMOS\n",
        "metamorphic": "MX2 N2 N3 N1 N1 PMOS\n",
        "counterexample": "M_PASS VOUT VG VIN VOUT PMOS\n",
    },
    "structure_floating_bias": {
        "canonical": "M_DIODE VBC VBC VSS VSS NMOS\nM_CASC_N NX VBC NY VSS NMOS\n",
        "metamorphic": "XI_BIAS_M4 N_B7 N_B7 VSS VSS NMOS\nXI_EA_M8 NX N_B7 NY VSS NMOS\n",
        "counterexample": "M_CASC_N NX VB_FLOAT NY VSS NMOS\nM_CASC_P NZ VB_FLOAT NW VDD PMOS\n",
    },
}

PROMPT = """# {title}

You are evaluating one original LDO engineering case. Read `inputs/case.json`{netlist_note}.

Return exactly one `answer.json` in this directory, following `answer_template.json`.

Rules:

1. Select `conclusion`, `analysis_regime`, and controlled array tokens only from the vocabulary in the case file.
2. State what is held fixed; do not infer a causal trend from a confounded sweep.
3. Use only supplied evidence. A simulator, license, parser, bench, measurement, and circuit failure are different classes.
4. `mechanism` and `claim_boundary` must be concise engineer-facing prose; hidden chain-of-thought is neither requested nor scored.
5. Do not use nodeset, forced initial conditions, ideal bias sources, or invented PDK data as a final circuit fix.
6. Do not access reference answers or oracles. Public development oracles are outside the runtime bundle and formal exams use a private store.
"""


def vocabulary_for(family: Dict[str, Any]) -> Dict[str, List[str]]:
    fields = ["conclusion", "analysis_regime", "held_fixed", "evidence_facts", "mechanism_tags", "recommended_actions", "forbidden_actions"]
    vocab: Dict[str, set] = {field: set() for field in fields}
    for item in family["variants"]:
        for field in fields:
            value = item["expected"][field]
            if isinstance(value, list):
                vocab[field].update(value)
            else:
                vocab[field].add(value)
    # Common distractors are intentionally generic and not answer-bearing.
    vocab["conclusion"].update(["insufficient_evidence", "no_change"])
    vocab["analysis_regime"].update(["connectivity", "dc_operating_point", "small_signal", "startup_transient", "execution_status"])
    return {field: sorted(values) for field, values in vocab.items()}


def make_oracle(task_id: str, family_id: str, exp: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "task_id": task_id,
        "family_id": family_id,
        "pass_threshold": 70,
        "critical_failure_cap": 49,
        "checks": [
            {"id": "task_identity", "path": "task_id", "kind": "exact", "expected": task_id, "weight": 5, "critical": True},
            {"id": "conclusion", "path": "conclusion", "kind": "exact", "expected": exp["conclusion"], "weight": 30, "critical": True},
            {"id": "analysis_regime", "path": "analysis_regime", "kind": "exact", "expected": exp["analysis_regime"], "weight": 10},
            {"id": "held_fixed", "path": "held_fixed", "kind": "set_contains", "expected": exp["held_fixed"], "weight": 10},
            {"id": "evidence_facts", "path": "evidence_facts", "kind": "set_contains", "expected": exp["evidence_facts"], "weight": 15},
            {"id": "mechanism_tags", "path": "mechanism_tags", "kind": "set_contains", "expected": exp["mechanism_tags"], "weight": 15},
            {"id": "recommended_actions", "path": "recommended_actions", "kind": "set_contains", "expected": exp["recommended_actions"], "weight": 10},
            {"id": "forbidden_actions", "path": "recommended_actions", "kind": "set_excludes", "expected": exp["forbidden_actions"], "weight": 5, "critical": True},
        ],
    }


def main() -> int:
    if TASKS_ROOT.exists():
        shutil.rmtree(TASKS_ROOT)
    if ORACLE_ROOT.exists():
        shutil.rmtree(ORACLE_ROOT)
    TASKS_ROOT.mkdir(parents=True)
    ORACLE_ROOT.mkdir(parents=True)
    registry_rows = []
    for family in FAMILIES:
        vocabulary = vocabulary_for(family)
        for item in family["variants"]:
            variant_name = item["name"]
            task_id = "%s--%s" % (family["family_id"], variant_name)
            task_dir = TASKS_ROOT / task_id
            (task_dir / "inputs").mkdir(parents=True)
            input_files = ["inputs/case.json"]
            case = {
                "schema_version": "1.0",
                "case_id": task_id,
                "family_id": family["family_id"],
                "variant": variant_name,
                "scenario": item["scenario"],
                "controlled_vocabulary": vocabulary,
            }
            (task_dir / "inputs" / "case.json").write_text(jd(case), encoding="utf-8")
            netlist = NETLISTS.get(family["family_id"], {}).get(variant_name)
            if netlist is not None:
                (task_dir / "inputs" / "circuit.sp").write_text(netlist, encoding="utf-8")
                input_files.append("inputs/circuit.sp")
            prompt = PROMPT.format(title=family["title"], netlist_note=" and `inputs/circuit.sp`" if netlist else "")
            (task_dir / "prompt.md").write_text(prompt, encoding="utf-8")
            answer_template = {
                "schema_version": "1.0",
                "task_id": task_id,
                "conclusion": "",
                "analysis_regime": "",
                "held_fixed": [],
                "evidence_facts": [],
                "mechanism_tags": [],
                "recommended_actions": [],
                "mechanism": "",
                "claim_boundary": "",
                "confidence": 0.0,
                "numeric_results": {},
            }
            (task_dir / "answer_template.json").write_text(jd(answer_template), encoding="utf-8")
            eligible_modes = ["direct_reasoning", "agentic_skill"]
            if family["suite"] in {"trend", "diagnosis", "design_closure"}:
                eligible_modes.append("simulation_assisted")
            if family["suite"] in {"sizing", "migration", "design_closure"}:
                eligible_modes.extend(["full_design", "weak_agent_airgap"])
            task = {
                "schema_version": "1.0",
                "task_id": task_id,
                "family_id": family["family_id"],
                "lineage_id": family["family_id"],
                "split": "dev",
                "variant": variant_name,
                "suite": family["suite"],
                "level": family["level"],
                "capabilities": family["capabilities"],
                "title": family["title"],
                "language": "en",
                "prompt_file": "prompt.md",
                "input_files": input_files,
                "answer_template_file": "answer_template.json",
                "eligible_modes": sorted(set(eligible_modes)),
                "budget": {"timeout_seconds": 300, "max_tool_calls": 0 if family["suite"] in {"structure", "sizing", "migration", "system_impact"} else 3},
                "variant_relationship": item["scenario"].get("changed_from_canonical", "unspecified"),
                "license": "CC-BY-4.0",
                "originality": "independently_authored_evoldo_bench",
            }
            (task_dir / "task.json").write_text(jd(task), encoding="utf-8")
            oracle = make_oracle(task_id, family["family_id"], item["expected"])
            oracle_path = ORACLE_ROOT / (task_id + ".oracle.json")
            oracle_path.write_text(jd(oracle), encoding="utf-8")
            digest = hashlib.sha256((task_dir / "task.json").read_bytes()).hexdigest()
            registry_rows.append({
                "task_id": task_id,
                "family_id": family["family_id"],
                "suite": family["suite"],
                "level": family["level"],
                "variant": variant_name,
                "split": "dev",
                "manifest_sha256": digest,
            })
    with REGISTRY.open("w", encoding="utf-8") as handle:
        for row in sorted(registry_rows, key=lambda value: value["task_id"]):
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    print("generated %d tasks in %d families" % (len(registry_rows), len(FAMILIES)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
