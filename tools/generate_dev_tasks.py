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

from generate_task_packages import package_reasoning_task

ROOT = Path(__file__).resolve().parents[1]
TASKS_ROOT = ROOT / "benchmarks" / "ldo_original" / "dev" / "tasks"
ORACLE_ROOT = ROOT / "benchmarks" / "ldo_original" / "dev_reference" / "oracles"
REGISTRY = ROOT / "benchmarks" / "ldo_original" / "registry.jsonl"


def jd(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def variant(name: str, scenario: Dict[str, Any], expected: Dict[str, Any]) -> Dict[str, Any]:
    return {"name": name, "scenario": scenario, "expected": expected}


def expected(conclusion: str, regime: str, held: List[str], facts: List[str], mechanisms: List[str], actions: List[str], forbidden: List[str]) -> Dict[str, Any]:
    def tokens(values: List[str]) -> List[str]:
        return ["_".join(value.split()) for value in values]

    return {
        "conclusion": conclusion,
        "analysis_regime": regime,
        "held_fixed": tokens(held),
        "evidence_facts": tokens(facts),
        "mechanism_tags": tokens(mechanisms),
        "recommended_actions": tokens(actions),
        "forbidden_actions": tokens(forbidden),
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


def pilot_family(
    family_id: str,
    suite: str,
    level: str,
    capabilities: List[str],
    title: str,
    canonical_case: Dict[str, Any],
    canonical_expected: Dict[str, Any],
    counter_case: Dict[str, Any],
    counter_expected: Dict[str, Any],
) -> Dict[str, Any]:
    """Build an original three-instance family for the controlled pilot.

    The metamorphic instance changes only representation. The counterexample changes one physical,
    evidential, or policy condition and therefore has its own answer.
    """
    metamorphic_case = {
        "evidence": canonical_case,
        "representation_transform": "symbols, ordering, and engineering-unit notation changed without changing the circuit facts",
        "changed_from_canonical": "representation only",
    }
    return {
        "family_id": family_id,
        "suite": suite,
        "level": level,
        "capabilities": capabilities,
        "title": title,
        "variants": [
            variant("canonical", {"evidence": canonical_case, "changed_from_canonical": "none"}, canonical_expected),
            variant("metamorphic", metamorphic_case, canonical_expected),
            variant("counterexample", {"evidence": counter_case, "changed_from_canonical": "one decision-relevant condition"}, counter_expected),
        ],
    }


# Phase-3 controlled-pilot families. All cases are independently authored and deliberately compact.
FAMILIES.extend([
    pilot_family(
        "structure_enable_polarity", "structure", "L1", ["structure", "startup_enable"],
        "Trace active-low enable polarity through a shutdown stack",
        {"enable_pin": "ENB", "active_level": 0, "shutdown_device": "PMOS opens bias path when gate is low"},
        expected("enable_path_valid", "connectivity", ["device_polarity", "supply_domains"], ["active_low_matches_pmos_switch", "bias_path_closes_when_enabled"], ["enable_truth_table_consistent"], ["verify_power_sequence_and_restart"], ["invert_enable_without_truth_table"]),
        {"enable_pin": "ENB", "active_level": 0, "shutdown_device": "NMOS opens bias path only when gate is high"},
        expected("enable_polarity_mismatch", "connectivity", ["device_polarity", "supply_domains"], ["active_low_does_not_turn_on_nmos_switch"], ["bias_remains_disconnected_when_commanded_on"], ["add_correct_polarity_stage", "rerun_enable_truth_table"], ["resize_bias_devices_first"]),
    ),
    pilot_family(
        "structure_current_mirror_direction", "structure", "L1", ["structure", "operating_point"],
        "Check current-mirror reference and output direction",
        {"mirror": "NMOS sink", "reference_branch": "diode-connected to positive reference current", "output_branch": "sinks from EA node"},
        expected("mirror_direction_valid", "connectivity", ["mos_polarity", "supply_orientation"], ["reference_establishes_positive_vgs", "output_branch_sinks_current"], ["shared_vgs_copies_sink_current"], ["verify_compliance_and_ratio"], ["reverse_reference_current"]),
        {"mirror": "NMOS sink", "reference_branch": "current forced out of diode node toward supply", "output_branch": "sinks from EA node"},
        expected("mirror_reference_reversed", "dc_operating_point", ["mos_polarity", "supply_orientation"], ["reference_cannot_establish_positive_vgs"], ["mirror_has_no_valid_bias_solution"], ["reverse_reference_branch direction", "rerun_operating_point"], ["force_gate_with_ideal_voltage"]),
    ),
    pilot_family(
        "structure_feedback_sense", "structure", "L1", ["structure", "feedback_stability"],
        "Verify that the divider senses the regulated output",
        {"divider_top": "VOUT", "divider_bottom": "VSS", "sense": "EA feedback input"},
        expected("feedback_sense_valid", "connectivity", ["divider_ratio", "ea_input_polarity"], ["divider_is_connected_to_vout", "sense_node_has_dc_path"], ["loop_observes_regulated_output"], ["verify_target_ratio_and_loop_sign"], ["compensate_before_connectivity_check"]),
        {"divider_top": "VIN", "divider_bottom": "VSS", "sense": "EA feedback input"},
        expected("feedback_senses_wrong_rail", "connectivity", ["divider_ratio", "ea_input_polarity"], ["divider_is_connected_to_vin_not_vout"], ["loop_does_not_observe_regulated_output"], ["reconnect_divider_top_to_vout"], ["tune_pass_width"]),
    ),
    pilot_family(
        "structure_supply_domain_isolation", "structure", "L2", ["structure", "migration"],
        "Detect an unsafe control signal crossing between supply domains",
        {"driver_domain_v": 0.8, "pass_gate_domain_v": 1.2, "level_shifter": "present", "off_state": "gate pulled to VIN"},
        expected("domain_crossing_valid", "connectivity", ["supply_ranges", "device_voltage_limits"], ["level_shifter_present", "off_state_tracks_high_rail"], ["gate_stress_and_false_turn_on_are_controlled"], ["verify_all_power_sequences"], ["remove_level_shifter_for_speed"]),
        {"driver_domain_v": 0.8, "pass_gate_domain_v": 1.2, "level_shifter": "absent", "off_state": "gate limited to 0.8 V"},
        expected("unsafe_domain_crossing", "dc_operating_point", ["supply_ranges", "device_voltage_limits"], ["gate_cannot_reach_high_rail", "device_stress_not_checked"], ["pass_device_may_remain_on_or_overstress_driver"], ["insert_qualified_level_shift_and clamp", "verify_power sequencing"], ["accept_nominal_only_operation"]),
    ),
    pilot_family(
        "trend_load_pole_shift", "trend", "L2", ["feedback_stability", "trend"],
        "Interpret output-pole motion across load current",
        {"load_ma": [1, 10, 100], "output_pole_khz": [5, 42, 310], "phase_margin_deg": [48, 61, 67], "held": ["cout", "esr", "loop_compensation"]},
        expected("load_moves_output_pole_up", "small_signal", ["cout", "esr", "loop_compensation"], ["output_pole_frequency_increases_with_load", "phase_margin_improves_in_supplied_range"], ["effective_output_resistance_falls_with_load"], ["verify_no_light_load instability"], ["generalize_beyond_supplied_load_range"]),
        {"load_ma": [1, 10, 100], "cout_pf": [50, 200, 1000], "output_pole_khz": [5, 8, 7], "held": ["esr", "loop_compensation"]},
        expected("load_pole_trend_confounded", "small_signal", ["esr", "loop_compensation"], ["load_and_cout_change_together"], ["pole_motion_cannot_be_attributed_to_load"], ["repeat_load sweep at fixed cout"], ["claim_load_causality"]),
    ),
    pilot_family(
        "trend_bias_gm_bandwidth", "trend", "L2", ["sizing", "feedback_stability"],
        "Explain error-amplifier bias current versus bandwidth and IQ",
        {"bias_ua": [2, 5, 12], "ugf_mhz": [1.8, 4.1, 8.0], "iq_ua": [9, 12, 19], "pm_deg": [59, 61, 60]},
        expected("bandwidth_improves_iq_cost", "small_signal", ["device_sizes", "compensation", "load"], ["ugf_increases", "iq_increases", "phase_margin_stays_similar"], ["transconductance_increases_with_bias"], ["select bias from speed and iq budgets"], ["maximize_bias_unconditionally"]),
        {"bias_ua": [2, 5, 12], "device_scale": [1, 2, 4], "ugf_mhz": [1.8, 4.0, 7.8]},
        expected("bias_effect_confounded_by_size", "small_signal", ["compensation", "load"], ["bias_and_device_size_change_together"], ["gm_and_capacitance_both_change"], ["repeat bias sweep at fixed geometry"], ["attribute_all_ugf_change_to_bias"]),
    ),
    pilot_family(
        "trend_feedforward_cap_regime", "trend", "L3", ["feedback_stability", "trend"],
        "Recognize the useful window of a feed-forward capacitor",
        {"cff_pf": [0, 0.2, 1.0], "pm_deg": [43, 66, 39], "peaking_db": [4.0, 0.8, 6.5]},
        expected("feedforward_cap_has_optimum_window", "small_signal", ["load", "divider", "compensation"], ["middle_value_has_best_margin", "large_value_increases_peaking"], ["zero_location_helps_then_high_frequency coupling_hurts"], ["search around middle value across corners"], ["assume_monotonic_improvement"]),
        {"cff_pf": [0, 0.2, 1.0], "pm_deg": [43, 54, 63], "peaking_db": [4.0, 2.3, 0.9]},
        expected("feedforward_cap_improves_supplied_range", "small_signal", ["load", "divider", "compensation"], ["phase_margin_rises", "peaking_falls"], ["zero_location_is_helpful_in_supplied_range"], ["verify_beyond_range_and_pvt"], ["claim_global_monotonicity"]),
    ),
    pilot_family(
        "trend_output_cap_esr", "trend", "L2", ["feedback_stability", "migration"],
        "Separate output-capacitance and ESR-zero effects",
        {"esr_ohm": [0.01, 0.3, 2.0], "cout_nf": 10, "pm_deg": [39, 64, 47]},
        expected("esr_has_stability_window", "small_signal", ["cout", "load", "loop_compensation"], ["middle_esr_has_best_margin"], ["esr_zero_can_add_phase_but_excess_esr_hurts"], ["qualify esr range not nominal point"], ["replace_cap_without_esr_model"]),
        {"esr_ohm": [0.01, 0.3, 2.0], "cout_nf": [1, 10, 100], "pm_deg": [39, 64, 47]},
        expected("esr_effect_confounded_by_cout", "small_signal", ["load", "loop_compensation"], ["esr_and_cout_change_together"], ["pole_and_zero_both_move"], ["run orthogonal cout and esr sweeps"], ["attribute_margin_to_esr_only"]),
    ),
    pilot_family(
        "trend_reference_filter", "trend", "L2", ["noise", "transient"],
        "Trade reference filtering against startup settling",
        {"filter_tau_us": [0.1, 1, 10], "output_noise_uvrms": [90, 48, 25], "startup_us": [1.2, 3.8, 24]},
        expected("reference_filter_reduces_noise_slows_startup", "noise_and_transient", ["reference_noise", "loop", "load"], ["noise_decreases", "startup_time_increases"], ["filter_bandwidth_rejects_noise_and_delays_reference"], ["choose tau from noise and startup limits"], ["maximize_tau_without_restart_test"]),
        {"filter_tau_us": [0.1, 1, 10], "output_noise_uvrms": [90, 48, 25], "startup_us": [1.2, 1.3, 1.2], "startup_bypass": "self_timed"},
        expected("startup_bypass_decouples_tradeoff", "noise_and_transient", ["reference_noise", "loop", "load"], ["noise_decreases", "startup_time_stays_flat"], ["physical_bypass_accelerates_reference_during_startup"], ["verify bypass turns off and restart works"], ["reuse_canonical_startup_penalty"]),
    ),
    pilot_family(
        "diagnosis_enable_vs_startup", "diagnosis", "L2", ["diagnosis", "startup_enable"],
        "Distinguish a disabled DUT from a genuine startup trap",
        {"sim_status": "completed", "enable_v": 0.0, "active_level_v": 0.8, "vout_v": 0.0},
        expected("dut_disabled", "dc_operating_point", ["dut", "models", "load"], ["enable_is_inactive", "simulation_completed"], ["zero_output_is_expected_when_disabled"], ["correct enable then rerun unchanged dut"], ["add_startup_branch"]),
        {"sim_status": "completed", "enable_v": 0.8, "active_level_v": 0.8, "seeded_op": "regulates", "cold_start": "stuck"},
        expected("startup_state_trap", "startup_transient", ["dut", "models", "load", "supply_ramp"], ["enable_is_active", "seeded_state_regulates", "cold_start_sticks"], ["physical_escape_path_is_missing"], ["add self_disabling startup path", "test restart"], ["change enable stimulus"]),
    ),
    pilot_family(
        "diagnosis_measurement_sign", "diagnosis", "L2", ["diagnosis", "evidence_integrity"],
        "Detect a sign convention error in load-current reporting",
        {"source_convention": "positive current enters positive terminal", "measured_a": -0.1, "load_draw_a": 0.1},
        expected("measurement_sign_is_consistent", "dc_operating_point", ["probe_orientation", "load"], ["negative_source_current_means_source_delivers_current"], ["reported_load_draw_is_magnitude"], ["document sign convention"], ["declare_negative_load"]),
        {"source_convention": "positive current enters positive terminal", "measured_a": 0.1, "report": "source delivers 0.1 A"},
        expected("measurement_sign_report_is_wrong", "dc_operating_point", ["probe_orientation", "load"], ["positive_source_current_means source_absorbs_current"], ["reported_direction contradicts convention"], ["correct report or probe orientation"], ["resize_pass_device"]),
    ),
    pilot_family(
        "diagnosis_stale_evidence", "diagnosis", "L3", ["evidence_integrity", "design_closure"],
        "Reject qualification evidence from an earlier candidate",
        {"candidate_hash": "B", "result_hash": "B", "result": "all gates pass"},
        expected("evidence_is_fresh", "execution_status", ["qualification_plan", "tool_version"], ["result_hash_matches_candidate"], ["evidence_is_bound_to_current_design"], ["permit promotion if all hard gates pass"], ["ignore_candidate_hash"]),
        {"candidate_hash": "B", "result_hash": "A", "result": "all gates pass"},
        expected("evidence_is_stale", "execution_status", ["qualification_plan", "tool_version"], ["result_hash_does_not_match_candidate"], ["old results cannot qualify new design"], ["rerun full qualification on candidate B"], ["promote_using_result_A"]),
    ),
    pilot_family(
        "diagnosis_convergence_vs_function", "diagnosis", "L2", ["diagnosis", "evidence_integrity"],
        "Separate numerical convergence failure from a functional miss",
        {"analysis": "dc", "status": "nonconverged", "iterations": "limit reached", "valid_results": False},
        expected("numerical_convergence_failure", "execution_status", ["netlist", "models", "solver_settings"], ["analysis_has_no_valid_result", "iteration_limit_reached"], ["functional performance is not observed"], ["diagnose topology and solver robustness", "rerun same candidate"], ["declare_voltage_spec_fail"]),
        {"analysis": "dc", "status": "completed", "vout_v": 0.61, "target_v": 0.8, "valid_results": True},
        expected("functional_regulation_failure", "dc_operating_point", ["netlist", "models", "load"], ["valid_result_exists", "vout_misses_target"], ["circuit operating point fails regulation"], ["audit headroom bias and loop state"], ["classify_as_solver_failure"]),
    ),
    pilot_family(
        "diagnosis_model_missing", "diagnosis", "L2", ["diagnosis", "migration"],
        "Classify an unresolved model card before simulation",
        {"elaboration": "failed", "message": "model identifier unresolved", "analyses_started": False},
        expected("model_mapping_failure", "execution_status", ["submitted_netlist", "model_include", "section"], ["elaboration_failed", "no_analysis_started"], ["missing model mapping is infrastructure configuration"], ["survey valid model and section", "rerun unchanged topology"], ["tune transistor sizes"]),
        {"elaboration": "passed", "analysis": "op complete", "device_regions": {"pass": "off"}},
        expected("circuit_bias_failure", "dc_operating_point", ["models", "bench", "load"], ["analysis_completed", "pass_device_is_off"], ["valid model evidence points to bias state"], ["trace enable and gate bias"], ["classify_as_model_mapping_failure"]),
    ),
    pilot_family(
        "sizing_driver_pass_coupling", "sizing", "L3", ["sizing", "feedback_stability"],
        "Size the pass device and gate driver as a coupled pair",
        {"pass_scale": 4, "driver_scale": 4, "dropout": "pass", "phase_margin": "pass", "iq": "pass"},
        expected("coupled_scaling_candidate_valid", "dc_small_signal_transient", ["driver_to_pass_ratio", "bias_density", "compensation"], ["dropout_and_margin_pass", "driver_tracks_gate_capacitance"], ["drive resistance and gate capacitance stay balanced"], ["qualify pvt and load corners"], ["increase_pass_only"]),
        {"pass_scale": 4, "driver_scale": 1, "dropout": "pass", "phase_margin": "fail", "gate_settling": "slow"},
        expected("driver_is_under_sized", "dc_small_signal_transient", ["bias_density", "compensation"], ["dropout_passes", "phase_margin_fails", "gate_settling_is_slow"], ["pass_gate capacitance exceeds driver capability"], ["co_optimize driver and compensation"], ["increase_pass_only"]),
    ),
    pilot_family(
        "sizing_cascode_headroom", "sizing", "L3", ["sizing", "operating_point"],
        "Decide whether cascoding is legal under the headroom budget",
        {"available_headroom_mv": 360, "required_stack_mv": 290, "all_devices_saturated": True},
        expected("cascode_headroom_valid", "dc_operating_point", ["supply", "common_mode", "load"], ["available_headroom_exceeds_required_stack", "devices_are_saturated"], ["cascode can provide gain in this regime"], ["verify worst_corner margin"], ["assume_nominal_headroom_everywhere"]),
        {"available_headroom_mv": 210, "required_stack_mv": 290, "all_devices_saturated": False},
        expected("cascode_headroom_invalid", "dc_operating_point", ["supply", "common_mode", "load"], ["required_stack_exceeds_headroom", "device_leaves_saturation"], ["extra stack loses gain and swing"], ["use lower_headroom gain technique or remove stack"], ["force node voltage ideally"]),
    ),
    pilot_family(
        "sizing_noise_iq", "sizing", "L3", ["sizing", "noise"],
        "Select an input-pair operating point from noise and IQ limits",
        {"bias_ua": [2, 6, 15], "noise_uvrms": [55, 31, 20], "total_iq_ua": [10, 14, 23], "limits": {"noise": 35, "iq": 18}},
        expected("middle_bias_is_feasible", "dc_and_noise", ["device_role", "bandwidth", "load"], ["middle_point_meets_noise_limit", "middle_point_meets_iq_limit"], ["higher_gm lowers input_noise at current cost"], ["select middle point then verify pvt"], ["choose_lowest_noise_without_iq_gate"]),
        {"bias_ua": [2, 6, 15], "noise_uvrms": [55, 31, 20], "total_iq_ua": [10, 14, 23], "limits": {"noise": 25, "iq": 18}},
        expected("no_swept_point_is_feasible", "dc_and_noise", ["device_role", "bandwidth", "load"], ["middle_fails_noise", "high_fails_iq"], ["objectives conflict in current search slice"], ["change device efficiency or architecture"], ["silently_violate_one_limit"]),
    ),
    pilot_family(
        "sizing_compensation_joint", "sizing", "L3", ["sizing", "feedback_stability"],
        "Use a coupled compensation search instead of one-knob tuning",
        {"variables": ["cc", "rzero"], "candidate": {"pm_deg": 63, "ugf_mhz": 8, "settling_us": 2.0}, "all_limits": "pass"},
        expected("joint_compensation_candidate_valid", "small_signal_and_transient", ["load", "pass_size", "driver"], ["phase_margin_passes", "bandwidth_passes", "settling_passes"], ["pole splitting and zero placement are co_optimized"], ["qualify across load and pvt"], ["freeze_rzero_before_search"]),
        {"variables": ["cc"], "candidate": {"pm_deg": 72, "ugf_mhz": 2, "settling_us": 8}, "limits": {"ugf_mhz_min": 5, "settling_us_max": 3}},
        expected("single_knob_solution_fails_speed", "small_signal_and_transient", ["load", "pass_size", "driver"], ["phase_margin_passes", "bandwidth_and_settling_fail"], ["excess dominant compensation trades away speed"], ["open rzero and driver coupled search"], ["accept_phase_margin_only"]),
    ),
    pilot_family(
        "migration_resistor_intent", "migration", "L2", ["migration", "sizing"],
        "Migrate a feedback resistor by ratio, noise, voltage and area intent",
        {"ratio_error_pct": 0.1, "voltage_rating": "pass", "noise": "pass", "area": "pass"},
        expected("resistor_migration_valid", "dc_and_noise", ["feedback_ratio", "current_budget", "temperature_range"], ["ratio_and_voltage_pass", "noise_and_area_pass"], ["electrical intent is preserved"], ["run extracted ratio and temp checks"], ["copy_geometry_only"]),
        {"ratio_error_pct": 0.1, "voltage_rating": "pass", "noise": "fail", "area": "pass"},
        expected("resistor_noise_intent_not_met", "noise", ["feedback_ratio", "current_budget", "temperature_range"], ["ratio_passes", "noise_fails"], ["matching ratio alone does not preserve noise"], ["select lower_noise resistor option or current"], ["approve_on_ratio_only"]),
    ),
    pilot_family(
        "migration_capacitor_intent", "migration", "L2", ["migration", "feedback_stability"],
        "Migrate a compensation capacitor with parasitic and voltage intent",
        {"cap_error_pct": 3, "voltage_rating": "pass", "bottom_plate_parasitic": "included", "pm": "pass"},
        expected("capacitor_migration_valid", "small_signal", ["connection_polarity", "load", "loop"], ["capacitance_and_voltage_pass", "parasitic_is_included"], ["migrated pole_zero locations are verified"], ["run pvt and extracted stability"], ["copy_nominal_cap_only"]),
        {"cap_error_pct": 3, "voltage_rating": "pass", "bottom_plate_parasitic": "ignored", "pm": "fail"},
        expected("capacitor_parasitic_breaks_stability", "small_signal", ["connection_polarity", "load", "loop"], ["nominal_cap_passes", "parasitic_was_ignored", "phase_margin_fails"], ["parasitic shifts the compensation network"], ["include parasitic and retune network"], ["approve_nominal_value_only"]),
    ),
    pilot_family(
        "migration_device_flavor", "migration", "L3", ["migration", "operating_point"],
        "Choose MOS flavor from headroom, leakage and speed constraints",
        {"flavor": "standard_threshold", "headroom": "pass", "leakage": "pass", "speed": "pass"},
        expected("device_flavor_valid", "dc_operating_point", ["geometry", "bias", "temperature"], ["headroom_leakage_speed_pass"], ["flavor satisfies the role constraints"], ["verify model corners and reliability"], ["pick_lowest_threshold_everywhere"]),
        {"flavor": "low_threshold", "headroom": "pass", "speed": "pass", "leakage": "fail_at_hot"},
        expected("device_flavor_leakage_failure", "dc_operating_point", ["geometry", "bias", "temperature"], ["speed_passes", "hot_leakage_fails"], ["threshold choice violates standby budget"], ["use role_specific threshold mix"], ["ignore_hot_leakage"]),
    ),
    pilot_family(
        "migration_corner_mapping", "migration", "L3", ["migration", "evidence_integrity"],
        "Validate semantic corner mapping instead of matching corner names",
        {"source_corner": "slow_n_slow_p_high_temp", "target_definition": "slow_n_slow_p_high_temp", "mapping": "semantic match"},
        expected("corner_mapping_valid", "execution_status", ["supply", "temperature", "model_release"], ["device_speed_and_temperature_semantics_match"], ["corner intent is preserved despite labels"], ["record section and model hashes"], ["map_by_short_name_only"]),
        {"source_corner": "slow_n_slow_p_high_temp", "target_definition": "fast_n_fast_p_low_temp", "mapping": "same short label"},
        expected("corner_mapping_invalid", "execution_status", ["supply", "temperature", "model_release"], ["short_label_matches_but_semantics_differ"], ["reported robustness covers wrong condition"], ["map from model definitions and temperature"], ["accept_label_match"]),
    ),
    pilot_family(
        "system_psrr_ripple", "system_impact", "L2", ["system_impact", "psrr"],
        "Propagate supply ripple through measured PSRR",
        {"input_ripple_mv": 20, "psrr_db": 40, "frequency_khz": 100},
        expected("output_ripple_is_0p2mv", "ac", ["frequency", "operating_point", "linearity"], ["psrr_is_100x_voltage_attenuation", "input_ripple_is_20mv"], ["output_ripple_equals_input divided_by_attenuation"], ["report 0p2mv and check downstream limit"], ["multiply_by_40"]),
        {"input_ripple_mv": 20, "psrr_db": 20, "frequency_khz": 100},
        expected("output_ripple_is_2mv", "ac", ["frequency", "operating_point", "linearity"], ["psrr_is_10x_voltage_attenuation", "input_ripple_is_20mv"], ["weaker_psrr passes_more_ripple"], ["report 2mv and check downstream limit"], ["reuse_0p2mv"]),
    ),
    pilot_family(
        "system_output_impedance", "system_impact", "L2", ["system_impact", "load_regulation"],
        "Convert output impedance into a load-step voltage estimate",
        {"zout_mohm": 80, "load_step_ma": 50, "frequency_regime": "quasi_static"},
        expected("estimated_droop_is_4mv", "dc", ["operating_point", "frequency_regime", "linearity"], ["zout_is_80mohm", "step_is_50ma"], ["delta_v_equals_zout_times_delta_i"], ["report 4mv estimate and verify transient"], ["claim_peak_transient_without_bandwidth"]),
        {"zout_mohm": 400, "load_step_ma": 50, "frequency_regime": "quasi_static"},
        expected("estimated_droop_is_20mv", "dc", ["operating_point", "frequency_regime", "linearity"], ["zout_is_400mohm", "step_is_50ma"], ["higher_zout increases_load_sensitivity"], ["report 20mv estimate and verify transient"], ["reuse_4mv"]),
    ),
    pilot_family(
        "design_closure_restart", "design_closure", "L3", ["startup_enable", "design_closure"],
        "Require shutdown-to-restart evidence in addition to first startup",
        {"cold_start": "pass", "shutdown": "pass", "restart": "pass", "final_state": "regulated"},
        expected("restart_sequence_valid", "startup_transient", ["supply_ramp", "enable_timing", "load"], ["cold_start_shutdown_restart_all_pass"], ["state machine escapes both initial and disabled states"], ["include sequence in pvt qualification"], ["claim_from_cold_start_only"]),
        {"cold_start": "pass", "shutdown": "pass", "restart": "stuck_low", "final_state": "off"},
        expected("restart_path_failure", "startup_transient", ["supply_ramp", "enable_timing", "load"], ["first_start_passes", "restart_fails"], ["shutdown leaves a trapped internal state"], ["fix physical reset or discharge path", "rerun sequence"], ["qualify_from_first_start"]),
    ),
    pilot_family(
        "design_closure_forbidden_ideal", "design_closure", "L3", ["design_closure", "policy"],
        "Apply the no-ideal-device hard gate to a final DUT",
        {"dut_devices": ["mos", "resistor", "mim_cap"], "ideal_sources_inside_dut": 0},
        expected("dut_policy_compliant", "connectivity", ["dut_hierarchy", "allowed_device_list"], ["no_ideal_sources_inside_dut"], ["all bias and startup functions are physically implemented"], ["retain hierarchy audit in qualification"], ["skip_forbidden_device_scan"]),
        {"dut_devices": ["mos", "resistor", "mim_cap", "ideal_current_source"], "ideal_sources_inside_dut": 1},
        expected("forbidden_ideal_device_present", "connectivity", ["dut_hierarchy", "allowed_device_list"], ["ideal_current_source_is_inside_dut"], ["performance depends on a forbidden implementation"], ["replace with physical bias circuit", "rerun all qualification"], ["waive_device_because_simulation_passes"]),
    ),
    pilot_family(
        "architecture_pass_device_choice", "architecture_choice", "L3", ["architecture_choice", "operating_point"],
        "Choose PMOS or NMOS pass topology from available rails and dropout",
        {"vin_v": 1.0, "vout_v": 0.8, "charge_pump_allowed": False, "candidate": "PMOS_high_side"},
        expected("pmos_pass_is_feasible_choice", "dc_operating_point", ["load", "device_options", "iq_budget"], ["pmos_gate_can_be_driven_below_source", "no_boost_rail_is_required"], ["pmos supports high_side operation within available rails"], ["size for dropout then verify stability"], ["choose_nmos_without_gate_headroom"]),
        {"vin_v": 1.0, "vout_v": 0.8, "charge_pump_allowed": False, "candidate": "NMOS_source_follower", "max_gate_v": 1.0},
        expected("nmos_gate_headroom_is_insufficient", "dc_operating_point", ["load", "device_options", "iq_budget"], ["gate_cannot_rise_above_input_rail", "source_target_is_close_to_input"], ["nmos_source_follower lacks required overdrive"], ["use pmos or approved boosted driver"], ["force_gate_above_supply_ideally"]),
    ),
    pilot_family(
        "architecture_loop_style_choice", "architecture_choice", "L4", ["architecture_choice", "feedback_stability"],
        "Choose a loop style for a wide load range and tight transient target",
        {"requirements": {"load_range": "1000x", "iq": "tight", "transient": "tight"}, "candidate": "fast_local_loop_plus_slow_accuracy_loop", "evidence": "separate loop bandwidths verified"},
        expected("dual_timescale_loop_is_supported", "small_signal_and_transient", ["load_range", "iq_budget", "output_cap"], ["local_and_global_loops_have_separated_bandwidths", "transient_and_accuracy_pass"], ["fast local action handles load while global loop restores accuracy"], ["verify interaction with nested loop breaks"], ["claim_stability_from_one_break_only"]),
        {"requirements": {"load_range": "1000x", "iq": "tight", "transient": "tight"}, "candidate": "dual_loop", "evidence": "only global loop measured"},
        expected("architecture_evidence_is_incomplete", "small_signal", ["load_range", "iq_budget", "output_cap"], ["local_loop_was_not_measured", "interaction_is_unknown"], ["one loop measurement cannot qualify nested loops"], ["measure each return ratio and closed_loop transient"], ["approve_from_global_margin_only"]),
    ),
])

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


def probe_policy_for(suite: str) -> Dict[str, Any]:
    mapping = {
        "structure": (["op", "dc"], ["operating_point"]),
        "trend": (["dc", "ac", "stb", "noise", "tran"], ["three_point_trend", "loop_gain", "noise_transfer", "transient_envelope"]),
        "diagnosis": (["op", "dc", "stb", "startup", "tran"], ["operating_point", "loop_gain", "startup_escape", "transient_envelope"]),
        "sizing": (["op", "dc", "stb", "noise", "tran"], ["operating_point", "three_point_trend", "loop_gain", "noise_transfer", "transient_envelope"]),
        "migration": (["op", "dc", "stb", "noise"], ["operating_point", "three_point_trend", "loop_gain", "noise_transfer"]),
        "system_impact": (["dc", "ac", "noise", "tran"], ["port_impedance", "noise_transfer", "transient_envelope"]),
        "design_closure": (["op", "dc", "stb", "noise", "tran", "startup"], ["operating_point", "loop_gain", "noise_transfer", "startup_escape", "transient_envelope"]),
        "architecture_choice": (["op", "dc", "stb", "tran", "startup"], ["operating_point", "loop_gain", "startup_escape", "transient_envelope"]),
    }
    regimes, families = mapping[suite]
    return {"allowed_regimes": regimes, "allowed_probe_families": families, "required_held_fixed": []}


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
            {"id": "held_fixed", "path": "held_fixed", "kind": "set_equals", "expected": exp["held_fixed"], "weight": 10},
            {"id": "evidence_facts", "path": "evidence_facts", "kind": "set_equals", "expected": exp["evidence_facts"], "weight": 15},
            {"id": "mechanism_tags", "path": "mechanism_tags", "kind": "set_equals", "expected": exp["mechanism_tags"], "weight": 15},
            {"id": "recommended_actions", "path": "recommended_actions", "kind": "set_equals", "expected": exp["recommended_actions"], "weight": 10},
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
            if family["suite"] != "structure":
                eligible_modes.append("simulation_assisted")
            if family["suite"] in {"sizing", "migration", "design_closure", "architecture_choice"}:
                eligible_modes.extend(["full_design", "weak_agent_airgap"])
            tool_budgets = {
                "structure": 0,
                "trend": 3,
                "diagnosis": 3,
                "sizing": 5,
                "migration": 5,
                "system_impact": 2,
                "design_closure": 8,
                "architecture_choice": 5,
            }
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
                "budget": {"timeout_seconds": 300, "max_tool_calls": tool_budgets[family["suite"]]},
                "probe_policy": probe_policy_for(family["suite"]),
                "variant_relationship": item["scenario"].get("changed_from_canonical", "unspecified"),
                "license": "CC-BY-4.0",
                "originality": "independently_authored_evoldo_bench",
            }
            (task_dir / "task.json").write_text(jd(task), encoding="utf-8")
            oracle = make_oracle(task_id, family["family_id"], item["expected"])
            oracle_path = ORACLE_ROOT / (task_id + ".oracle.json")
            oracle_path.write_text(jd(oracle), encoding="utf-8")
            package_digest = package_reasoning_task(task_dir, oracle_path)
            digest = hashlib.sha256((task_dir / "task.json").read_bytes()).hexdigest()
            registry_rows.append({
                "task_id": task_id,
                "family_id": family["family_id"],
                "suite": family["suite"],
                "level": family["level"],
                "variant": variant_name,
                "split": "dev",
                "manifest_sha256": digest,
                "package_sha256": package_digest,
            })
    with REGISTRY.open("w", encoding="utf-8") as handle:
        for row in sorted(registry_rows, key=lambda value: value["task_id"]):
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    print("generated %d tasks in %d families" % (len(registry_rows), len(FAMILIES)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
