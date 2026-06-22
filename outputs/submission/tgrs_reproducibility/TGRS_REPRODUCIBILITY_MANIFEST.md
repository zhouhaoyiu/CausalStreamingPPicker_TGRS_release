# TGRS Reproducibility Manifest

Generated: 2026-06-21T05:11:31
Repository: `<repository-root>`
Public repository: `https://github.com/zhouhaoyiu/CausalStreamingPPicker_TGRS_release`
Public release tag: `v0.5-tgrs-submission`

## Claim Scope

- This manifest records the current reproducibility state for the TGRS manuscript.
- Public waveform data should be obtained from the original providers; raw third-party waveforms are not redistributed here.
- PNWAccelerometers is the current no-manual external labeled-accelerometer check; high-SNR near-P results and unfiltered random-record results are both retained.
- External label-building materials that have not passed P-reference validation are not part of the current TGRS accuracy claim.
- The domestic 2021 M>=5 pilot intake currently contains templates and a strict validator; no domestic accuracy result exists until accepted records are exported by `validate_domestic_strong_motion_pilot.py`.
- Conditional artifacts, especially checkpoints and third-party baseline outputs, require license and release review before public archiving.

## Current Preflight

```text
TGRS preflight: PASS=138 WARN=1 FAIL=0
<repository-root>/outputs/submission/tgrs_preflight_report.md
```

## PDF Info

```text
Creator:         TeX
Producer:        pdfTeX-1.40.28
CreationDate:    Sun Jun 21 05:11:11 2026 CST
ModDate:         Sun Jun 21 05:11:11 2026 CST
Custom Metadata: yes
Metadata Stream: no
Tagged:          no
UserProperties:  no
Suspects:        no
Form:            none
JavaScript:      no
Pages:           15
Encrypted:       no
Page size:       612 x 792 pts (letter)
Page rot:        0
File size:       686205 bytes
Optimized:       no
PDF version:     1.7
```

## Rebuild Commands

| step | command |
| --- | --- |
| Build English manuscript | cd paper/tgrs && latexmk -pdf -interaction=nonstopmode -halt-on-error tgrs_causal_streaming_picker.tex |
| Build Chinese review manuscript | cd paper/tgrs && latexmk -xelatex -interaction=nonstopmode -halt-on-error tgrs_causal_streaming_picker_cn.tex |
| Regenerate TGRS figures | <zhy-python> paper/tgrs/revision/plot_tgrs_figures.py |
| Run spike-injected false-trigger stress test | <zhy-python> scripts/evaluation/eval_spike_false_alarm_stress.py --device cpu --thresholds 0.55 --confirm-list 1,2,3 |
| Run post-hoc artifact gate audit | <zhy-python> scripts/evaluation/eval_artifact_gate_operating_points.py |
| Run STEAD labeled-noise station-time false-trigger replay | <zhy-python> scripts/evaluation/eval_stead_noise_stationday_false_alarm.py --max-traces 3000 --station-limit 300 --min-traces-per-station 5 --device mps |
| Run PNWAccelerometers high-SNR near-P-arrival external check | <zhy-python> scripts/evaluation/eval_cwa_tsmip_external.py --dataset PNWAccelerometers --max-samples 2000 --max-chunks 320 --threshold 0.55 --confirm-chunks 2 --min-snr-db 20 --decision-start-offset-chunks -3 --tag pnwaccelerometers_theta055_confirm2_firstp_n2000_snr20_max320_plocal_m3 --device cpu |
| Run PNWAccelerometers unfiltered random-record check | <zhy-python> scripts/evaluation/eval_cwa_tsmip_external.py --dataset PNWAccelerometers --max-samples 2000 --max-chunks 320 --threshold 0.55 --confirm-chunks 2 --tag pnwaccelerometers_theta055_confirm2_firstp_n2000_max320 --device cpu |
| Run FDSN continuous strong-motion station-day false-trigger campaign | <zhy-python> scripts/evaluation/run_fdsn_strong_motion_stationday_campaign.py --starts 2024-01-03T00:00:00,2024-02-07T00:00:00,2024-03-12T00:00:00,2024-05-21T00:00:00 --stations PASC,SVD,USC,WTT2,CAC,FON,CFS,CJV2,LAF,LDR --duration-hours 6 --download-chunk-hours 1 --device mps --output-dir outputs/evaluation/fdsn_strong_motion_stationday_campaign_stable10 |
| Run FDSN one-hour continuous strong-motion extension campaign | <zhy-python> scripts/evaluation/run_fdsn_strong_motion_stationday_campaign.py --starts 2024-06-18T00:00:00,2024-07-23T00:00:00,2024-08-28T00:00:00,2024-09-17T00:00:00,2024-10-22T00:00:00,2024-11-19T00:00:00,2024-12-10T00:00:00 --stations PASC,SVD,USC,WTT2,CAC,FON,CFS,CJV2,LAF,LDR --duration-hours 1 --download-chunk-hours 1 --device mps --output-dir outputs/evaluation/fdsn_strong_motion_stationday_campaign_extra1h |
| Combine FDSN continuous strong-motion campaigns | <zhy-python> scripts/evaluation/combine_fdsn_campaign_summaries.py |
| Run K-NET M>=4 Delaunay-neighbor association gate | <zhy-python> scripts/evaluation/eval_knet_delaunay_association_gate.py --details outputs/evaluation/confirmation_effect/knet_test_mge4_dle200_details.csv --metadata data/knet_accel/metadata.csv --output-dir outputs/evaluation/delaunay_association --tag knet_mge4_dle200 --dataset-label 'K-NET test split, M >= 4, source distance <= 200 km' |
| Run K-NET M<4 Delaunay-neighbor association gate | <zhy-python> scripts/evaluation/eval_knet_delaunay_association_gate.py --details outputs/evaluation/confirmation_effect/knet_test_lt4_dle200_details.csv --metadata data/knet_accel/metadata.csv --output-dir outputs/evaluation/delaunay_association --tag knet_lt4_dle200 --dataset-label 'K-NET test split, M < 4, source distance <= 200 km' |
| Regenerate detailed TGRS result tables | <zhy-python> paper/tgrs/revision/build_detailed_result_tables.py |
| Run TGRS preflight | <zhy-python> paper/tgrs/preflight_tgrs_submission.py |
| Build TGRS supplement release archive | <zhy-python> paper/tgrs/build_tgrs_supplement_release.py |
| Validate domestic 2021 M>=5 strong-motion pilot intake | <zhy-python> scripts/data/validate_domestic_strong_motion_pilot.py |
| Build confidence intervals | <zhy-python> scripts/evaluation/build_tgrs_confidence_intervals.py |

## Artifact Inventory

| path | role | exists | bytes | sha256 | public |
| --- | --- | --- | --- | --- | --- |
| paper/tgrs/tgrs_causal_streaming_picker.pdf | manuscript | yes | 686205 | 29f69067f8f0ec5988baaca6e8adc71ad80b74c9ebf6ce8a26a5cb49645f3e93 | yes |
| paper/tgrs/tgrs_causal_streaming_picker.tex | manuscript_source | yes | 62715 | 2db9d0864e97c84e47711e6b4275606555df26a9ebc9bd6b650f74a35e796333 | yes |
| paper/tgrs/tgrs_causal_streaming_picker_cn.pdf | internal_review | yes | 727226 | 36a64248405594074c313a62c4b08638a07e28457f82276a1b9e9299c8b48e38 | no |
| paper/tgrs/references.bib | bibliography | yes | 29690 | 8003a79c8c28201334f78df4a61c318bb4efa07f98ba72a78576dc35299b35ef | yes |
| paper/tgrs/cover_letter_tgrs.md | submission | yes | 4506 | 77929ed7fe9ad9d9d7d16fddc0accd5abe25220a3b02fd60a62083e66cf38417 | yes |
| paper/tgrs/cover_letter_tgrs.txt | submission | yes | 4419 | 713fe09e441c03d8a323d407497f8c7cbfe6f1ed32c05dbb2874da17572ba767 | yes |
| paper/tgrs/submission_portal_fields_tgrs.md | submission | yes | 4544 | 74618be3c061f58a82e54ef46c924e8143a5d67f8b8b890b157bfc5809f3fabf | yes |
| paper/tgrs/reproducibility/README.md | release_metadata | yes | 639 | 8d47a2d8129ee77f06ad6da5b01d69a5c7b7d9727bf77c86a250aa2de4d52b7d | yes |
| paper/tgrs/reproducibility/LICENSE | release_metadata | yes | 1067 | a083074bc5725255331d5cf80691ca44145da891af2da54fb4e5eb50e006dfbc | yes |
| paper/tgrs/reproducibility/MODEL_LICENSE | release_metadata | yes | 494 | eec62a1786a92f6307e71432f1d9be659caa9cde791c133dcda760a57a09321c | yes |
| paper/tgrs/reproducibility/CITATION.cff | release_metadata | yes | 938 | 1911a837c5b1e5eef0b94a00b885fcedff922a9551f81315d5895a0b3db42900 | yes |
| paper/tgrs/preflight_tgrs_submission.py | quality_gate | yes | 29952 | be60d4cf8a42aabf84dd6865c9fb5505d14ceff964805488b1c7c0df9b57fc50 | yes |
| paper/tgrs/build_tgrs_supplement_release.py | release_packaging | yes | 6520 | 27a6f753d75d94811cd67b94ccc4ec19171555c411d7902b3dd9cca350995243 | yes |
| outputs/submission/tgrs_preflight_report.md | quality_gate_output | yes | 12353 | 56a24070264f6e64e163c917538cb953b42f5b83ab6b7c7112578130176694c5 | yes |
| outputs/submission/tgrs_supplement_release/CausalStreamingPPicker_TGRS_supplement.zip | release_archive | yes | 10923792 | a9de448c75f5834d164402a07fc2a20a140bd5b33165a9dfe7faedcbd9cc1e37 | yes |
| paper/tgrs/revision/eqanomalynet_style_lessons.md | internal_review | yes | 14877 | 5062b0b2b9ccdfe3074c1477b1e65f98c8a5a7f838563bf60b072bd749e84bd6 | no |
| paper/tgrs/revision/manuscript_evidence_coverage_audit.md | internal_review | yes | 7973 | 0a14faad50b2604b3ba3371bc853c4f3daf35af0325239b1defa5db7cd738590 | no |
| paper/tgrs/revision/plot_tgrs_figures.py | figure_generation | yes | 55392 | aa04d905270daf6e01f1c9eeca515f08250f4bbb4df294ae6c59e80ed8c06f29 | yes |
| paper/tgrs/plot_knet_column_figure.py | figure_generation | yes | 29849 | 6cb42eb5bf02e0b7afc6f5c84d4f4eeee960dafd0e86f470a209ebc72b0ef9bd | yes |
| paper/tgrs/revision/build_detailed_result_tables.py | table_generation | yes | 21065 | 831f42b75c13b10e19c88d066878997cb8a0d452e19daacb9257189de4a7b177 | yes |
| paper/tgrs/figures/fig_task_positioning_en.pdf | figure | yes | 67274 | 3a5aa68bc3a0d4aaaa452a9772ea6ea52f06473be7c24e0b03ec9bf46f57b406 | yes |
| paper/tgrs/figures/fig_architecture_en.pdf | figure | yes | 47121 | 094d9b991393259c12da680159c188052a0b90a6ebc414f4fe74d067f90cd380 | yes |
| paper/tgrs/figures/fig1_firstp_latency_en_column.pdf | figure | yes | 18802 | f10f4691de39441812918e679731c4b543e7803d3277f47fa75262b047c3a0e0 | yes |
| paper/tgrs/figures/fig_causal_replay_case_en.pdf | figure | yes | 96242 | 1abcfe5953e8cf716d3bc65d707f6aad943801c122312814804a2e5d7d297c5e | yes |
| paper/tgrs/figures/fig2_knet_bins_en_column.pdf | figure | yes | 32119 | 609b244cdafa87be1f87bf7b3a93c942572ac28491d980e5c9ea9defc4da1438 | yes |
| paper/tgrs/figures/fig_knet_imperfect_association_en.pdf | figure | yes | 75022 | 19f76bfa4a91a6b858f80dca3ccdcbe1ffb17d7c8abbbc67abfc7030963e73bc | yes |
| paper/tgrs/figures/fig_operating_tradeoff_en.pdf | figure | yes | 72757 | 17858fac7dbad5e64b0a519d95e31260bc345957f02f681d00913c6a4b285915 | yes |
| paper/tgrs/figures/fig_spike_response_map_en.pdf | figure | yes | 94330 | 2566968df5dab222a48c44799ab0e9c859b2210641ca46f157663a576ea0084a | yes |
| paper/tgrs/figures/source_firstp.csv | figure_source | yes | 203 | b19bfa4d0cb2aa8734d68b2dfa85bb5a7fd12a17d3d5e9699fbc8eea61a6589c | yes |
| paper/tgrs/figures/source_knet_categories.csv | figure_source | yes | 129 | 7be21e8531c8a5a9f042a5d27ac8a6f45c827c5fa9bf8f2b7377030dcac9942e | yes |
| paper/tgrs/figures/source_knet_by_magnitude.csv | figure_source | yes | 154 | 4f5c6cff1c636d07b47d04123babf74cea651450feb11af0400e59803aa88b29 | yes |
| paper/tgrs/figures/source_knet_by_distance.csv | figure_source | yes | 184 | bec94960335dea3b2712682120e11fe9c4c8b4139e012f8d8a4819c218753d86 | yes |
| paper/tgrs/figures/source_redpan_knet_comparison.csv | figure_source | yes | 481 | 2da6f57aa02db9343c22e226f3ce070762fe5708f1c9c3305fbbc2457d5bff19 | yes |
| paper/tgrs/figures/source_ablation.csv | figure_source | yes | 175 | 43109e9f955047008e1067b2e4b45b80d371a09903fb4dd963f0e8497ec6de2d | yes |
| paper/tgrs/figures/source_causal_replay_case.csv | figure_source | yes | 36355 | 4a2632104e2ad49008db39dcb64a52777780c55c5739b8dc4f824c7b5da0d86e | yes |
| paper/tgrs/figures/source_operating_tradeoff.csv | figure_source | yes | 3138 | 9b252ec7d9f564f8d18823fe981fbab71b9bfdbe6df1b02dcaf1ed372ef2c8dd | yes |
| paper/tgrs/figures/source_spike_response_map.csv | figure_source | yes | 1940190 | e4355e7c699f4aaafd1f97f70cf8e8cbbece1b4a9eabb396a1155a3ef7c4458e | yes |
| paper/tgrs/figures/source_station_detailed_metrics.csv | table_source | yes | 1733 | e1c51a5aaa14e9e0fdb2390a876501d625b6c9001b9267a557222d836db9430a | yes |
| paper/tgrs/figures/source_knet_stratified_detailed_metrics.csv | table_source | yes | 1359 | d50893bfb3ba0b2c5ebb71eaa09cd47e72aeb438a9e0197bd51d9fb7120ad1d0 | yes |
| paper/tgrs/figures/source_confirmation_operating_metrics.csv | table_source | yes | 591 | 9ba6cf6beeb7b9b552511b38367ecd53bd5f83adf3abc40f958f50f575532a7a | yes |
| paper/tgrs/figures/source_knet_association_operating_point.csv | table_source | yes | 1036 | d72fa67fe9829155a30d0c0827a348f38363bb433a39f6d6d0babc54b31808cd | yes |
| paper/tgrs/figures/source_spike_false_alarm_stress.csv | table_source | yes | 1700 | 49047fcba61b948557c72e1a8f800184a6e754c6739e157bd41bd30284e9537e | yes |
| paper/tgrs/figures/table_station_detailed_metrics_en.tex | table_source | yes | 1611 | 09db4acb12970d14a70e5e6682fb9a6920c212fcf98d5f026f15a19b691b6f7a | yes |
| paper/tgrs/figures/table_knet_stratified_detailed_en.tex | table_source | yes | 1199 | 81dd11b52786fd656fe099279695747d2acd3dee6294fec0027b09e0962e44c1 | yes |
| paper/tgrs/figures/table_spike_false_alarm_en.tex | table_source | yes | 1096 | 8ff64dad5632e3b74341aaeb880e69bc5624508b2cfc7d0e88f46c2ec7f7b9ef | yes |
| paper/tgrs/figures/table_continuous_false_alarm_en.tex | table_source | yes | 1391 | 6d9cc42a7d226f73d24beb73b0bef35bd63b85475fcee9a3eee501e27db257bf | yes |
| paper/tgrs/figures/table_stead_noise_false_alarm_en.tex | table_source | yes | 802 | 138725e98370d1257b85b71c072faec1744946fccd3c69dff1aa1e4d16b57cf3 | yes |
| paper/tgrs/figures/table_stead_noise_false_alarm_cn.tex | internal_review | yes | 832 | fd8719ae549db426510816fb053672c32c024391d77ed85f75f03d8dbbee2e48 | no |
| paper/tgrs/figures/table_fdsn_continuous_false_alarm_en.tex | table_source | yes | 1098 | 9aaaa6b2df86d04d6e2038eceb17c6aacaa7c5d68acc5e633c7d7ade823fa82d | yes |
| paper/tgrs/figures/table_fdsn_continuous_false_alarm_cn.tex | internal_review | yes | 968 | 324629934e405276ae4c94814b0954559e72270461354a99343d9878c8ce03fa | no |
| paper/tgrs/external_evidence_closure_honest_20260617.tex | manuscript_source | yes | 3485 | 357bf65f0824de9c32c1ce298891bb4de3f01a9a4f894d7d141abc26d0b1819e | yes |
| paper/tgrs/external_evidence_closure_honest_20260617_cn.md | internal_review | yes | 1280 | 3351c88200482f0e89397899ace41abd8fc25cd5b111655e726ecb9183a64804 | no |
| models/checkpoints/multidomain_best.pt | checkpoint | yes | 1132970 | 4e2dfa897410b77629440602b4e5404479ede7b7459db87ab862cacd7372b51d | conditional |
| models/checkpoints/causal_v3_epoch3.pt | checkpoint | yes | 1132489 | eab6220840f69b0428fc94bcba8338256e09e65dc81129c3a530526e009d584e | conditional |
| src/model_impl.py | model_code | yes | 11534 | 1bc4c632b9526b1e00269c89e50b93b2e55747ccf5aa3f29e7b9d87cb70de0db | yes |
| src/model.py | model_code | yes | 184 | f0dc6a04b603f0ce23e4ef1d9124411cce1c3508d6a379d73ebefc619eec046c | yes |
| scripts/training/mpstrain_multidomain.py | training_code | yes | 37503 | eb8601d9b427e4fee0264c5fb69619d1c52d9ba690e9a9f003e9c74c26cde1ae | yes |
| scripts/evaluation/eval_multidomain_test.py | evaluation_code | yes | 23355 | b1782e9918a5d68450e5038d7bcaee21d4add0043f5b4b554b648d565fe97dd9 | yes |
| scripts/evaluation/eval_prefilled_window_baselines.py | evaluation_code | yes | 14481 | 2c97a4eb421da390e47d3726f2646c89bb3938bd9278813b145b4bdcfa8c70ec | yes |
| scripts/evaluation/eval_knet_confirmation_effect.py | evaluation_code | yes | 18298 | f7ceb23e5984981d4cc11cb99bd115005832b30f6e246f0a7c0a56ae17592345 | yes |
| scripts/evaluation/eval_continuous_false_alarm_sim.py | evaluation_code | yes | 16894 | 4a126ecf12f1d9e381dedd63e37118832ab15c46b8f0307a54ba1f66fae84a03 | yes |
| scripts/evaluation/eval_spike_false_alarm_stress.py | evaluation_code | yes | 18128 | efb3c37ebed155425f8733b858fa7c6f5d0fe7e4b1cc0f52e940d12e8ac06823 | yes |
| scripts/evaluation/eval_artifact_gate_operating_points.py | evaluation_code | yes | 29828 | a3d83d286bbabe07753b32ba2ff7ffc33c39157ca70a70a12708a77ea91e12b7 | yes |
| scripts/evaluation/eval_stead_noise_stationday_false_alarm.py | evaluation_code | yes | 25506 | e7a6b4f5ce6a273311f57ba674f53c62461f67e4e1a88e53b85cee92735fc8e2 | yes |
| scripts/evaluation/eval_cwa_tsmip_external.py | evaluation_code | yes | 14629 | 8f0e2496663380cdc087722a9ba9b1da345f408d2220d6387663fe31023a88ca | yes |
| scripts/evaluation/eval_fdsn_strong_motion_stationday_false_alarm.py | evaluation_code | yes | 34856 | 5cc1f1f21c36031824a618232c455e2dc412eb73379bbdce9614140e1cb4b683 | yes |
| scripts/evaluation/run_fdsn_strong_motion_stationday_campaign.py | evaluation_code | yes | 11210 | 8b61d7e236a17304ed0c10274024a7a5b51128fd10184084227122a5b19ab665 | yes |
| scripts/evaluation/combine_fdsn_campaign_summaries.py | analysis_code | yes | 6824 | 45baeea963fa66dbdb933771e941765fc9d65dca30cddbbe0fd4a96f751a5782 | yes |
| scripts/evaluation/eval_knet_network_association_sim.py | evaluation_code | yes | 15202 | 82a40c5375486b5279af69cd26c265e7fcda8c608dc4cd78577a9f0f4852062b | yes |
| scripts/evaluation/eval_knet_delaunay_association_gate.py | evaluation_code | yes | 18540 | 2c440e8e722f2475eeeca87b7549fc87c30836f48756c1240989ed5e2c77a3ab | yes |
| scripts/evaluation/build_tgrs_confidence_intervals.py | analysis_code | yes | 17997 | 7f6668469b6453703554588666d0f27104fc015cde8dc36e9db03a02847f16a1 | yes |
| outputs/evaluation/tgrs_confidence_intervals/tgrs_confidence_intervals.md | analysis_output | yes | 15880 | eae7ec2c9904424d72d1bc011d89559991af46141d602956521a380fa147b51d | yes |
| outputs/evaluation/confirmation_effect/knet_test_mge4_dle200_report.md | analysis_output | yes | 3677 | 15eeef3a7f4e5e512b1654681528759f37c115680ccff0b7998d2ff2fea8ffe8 | yes |
| outputs/evaluation/continuous_false_alarm/continuous_false_alarm_report.md | analysis_output | yes | 3620 | c24ba9f73a101f70c224d5b56dd7cb737864c77743c73182eb919cd95329848e | yes |
| outputs/evaluation/spike_false_alarm_stress/spike_false_alarm_stress_report.md | analysis_output | yes | 2823 | 7b4f2fa39b4c5cac9d13a0e82096dc4d7705c591c2c133c42184f6822132f19a | yes |
| outputs/evaluation/spike_false_alarm_stress/spike_false_alarm_stress_summary.csv | analysis_output | yes | 1712 | 38125ede5668c2309f5658f0ee1290ce3e9925b80838fc16940dd14e1432b4d9 | yes |
| outputs/evaluation/artifact_gate_operating_points/artifact_gate_operating_points_report.md | analysis_output | yes | 4453 | 9d6e4a147fc1c6230e7bfb8b96101a69bba6d3c5600c6812e5748c52db6e3076 | yes |
| outputs/evaluation/artifact_gate_operating_points/spike_gate_summary.csv | analysis_output | yes | 6526 | 2e41c582f59e7008e86cd0bab1d84503992c534cb6872ce9b09b7a986845ad9c | yes |
| outputs/evaluation/artifact_gate_operating_points/knet_event_candidate_gate_survival.csv | analysis_output | yes | 789 | 0599d0cb9f774f16611b626aa340b0045232e9c6e89c3c3ca903441bb25d38c0 | yes |
| outputs/evaluation/artifact_gate_operating_points/pseudo_network_coincidence_summary.csv | analysis_output | yes | 9199 | 1f15f3d6f656d7bec6d0bbb217648ba2b840a83fac3ee27826d1ba3c7cd103ce | yes |
| outputs/evaluation/stead_noise_stationday_false_alarm/stead_noise_stationday_false_alarm_report.md | analysis_output | yes | 2630 | d6eb74720f0fe6d9f782565adf7a1bd9ffabde3c4ec9fb238b39bb5b7cc369aa | yes |
| outputs/evaluation/stead_noise_stationday_false_alarm/stationday_false_alarm_rates.csv | analysis_output | yes | 1658 | 819ec1d65786105476eeb7b8bada9883cca7766d9bca8a3ed1f54dd293007df8 | yes |
| outputs/evaluation/stead_noise_stationday_false_alarm/noise_timestamp_coincidence_summary.csv | analysis_output | yes | 2849 | a6c4b282292b23ed226b78e4264e702c7de9f1ed585a9c83ec1347f6b61d7ee1 | yes |
| outputs/evaluation/external_labeled_accel_smoke/tgrs_external_evidence_closure_20260617_cn.md | analysis_output | yes | 7101 | 1723ca89aa05c772f789e076a664473fb7b07564ca23a07b523f66fa4d905f7c | yes |
| outputs/evaluation/external_labeled_accel_smoke/pnwaccelerometers_theta055_confirm2_firstp_n2000_snr20_max320_plocal_m3_summary.txt | analysis_output | yes | 685 | 4e55fe901981c745cca9176dd7037545f1badc7a598ae6598f49d4a10d74cace | yes |
| outputs/evaluation/external_labeled_accel_smoke/pnwaccelerometers_theta055_confirm2_firstp_n2000_snr20_max320_plocal_m3_summary.json | analysis_output | yes | 501 | 4da678291e9cecb30e213a5bed56c33cf2d34770f381663565d9ced3dbbe4f2d | yes |
| outputs/evaluation/external_labeled_accel_smoke/pnwaccelerometers_theta055_confirm2_firstp_n2000_max320_summary.txt | analysis_output | yes | 686 | 9e5c205eb796b05e15fa2c9995295842107a67076cee93ce450ee3cd9b78d961 | yes |
| outputs/evaluation/external_labeled_accel_smoke/pnwaccelerometers_theta055_confirm2_firstp_n2000_max320_summary.json | analysis_output | yes | 484 | 9a5ae2e298d5ee4323ba03364c9c4c68ac685f8f6a0da00f92dfbccfeb7bae2c | yes |
| outputs/evaluation/external_labeled_accel_smoke/pnwacc_plocal_m3_n500_snr20_theta045_summary.txt | analysis_output | yes | 634 | 10286ab4edcde061cb9206d2053caf5424188a3c12339f9ab64d4340e55c77ee | yes |
| outputs/evaluation/external_labeled_accel_smoke/pnwacc_plocal_m3_n500_snr20_theta050_summary.txt | analysis_output | yes | 633 | 220cc7547909e7e892e7ba5e6cc3fc2e278f0b26efca65f72f7add72afb639af | yes |
| outputs/evaluation/external_labeled_accel_smoke/pnwacc_plocal_m3_n500_snr20_theta060_summary.txt | analysis_output | yes | 633 | 663a9e2b8e9262dc2ecda216c1464ef94c26a511217552881301bd6b75affdb7 | yes |
| outputs/evaluation/fdsn_strong_motion_stationday_false_alarm/fdsn_strong_motion_stationday_false_alarm_report.md | analysis_output | yes | 2260 | 8193565712b121e308bf60829a63e098e112800a8826e77b566e1dd95fb9ebf2 | yes |
| outputs/evaluation/fdsn_strong_motion_stationday_false_alarm/stationday_false_alarm_rates.csv | analysis_output | yes | 1413 | feb3ba757a4629c84165d366a14bef726ce468bc94dcc1e12dec911fe9612fa0 | yes |
| outputs/evaluation/fdsn_strong_motion_stationday_false_alarm/network_coincidence_summary.csv | analysis_output | yes | 1891 | 8695816871ce1a7bced791cea94c2aef6e81ad443d21fbc52c9a19cc62a5e26a | yes |
| outputs/evaluation/fdsn_strong_motion_stationday_false_alarm/event_catalog_screen.csv | analysis_output | yes | 67 | d263072790aac1f955b012617f18e912554ccb1778fa80ecfcbfbaa4109b0362 | yes |
| outputs/evaluation/fdsn_strong_motion_stationday_campaign_stable10/campaign_report.md | analysis_output | yes | 1525 | c5973d4eb6425fa8fdfa6ada162e8365c58e9cc551e9f540b1ae9d79df4d31bd | yes |
| outputs/evaluation/fdsn_strong_motion_stationday_campaign_stable10/campaign_stationday_false_alarm_rates.csv | analysis_output | yes | 1410 | 26566a34c464d541f4e86371914dfbe943fc51c3917f8deb42a49349056e3828 | yes |
| outputs/evaluation/fdsn_strong_motion_stationday_campaign_stable10/campaign_network_coincidence_summary.csv | analysis_output | yes | 2215 | 00cc848a7e3dd4d1ae0b3d4179d0996cc37ff55de0d34b9ccba792680cfcee69 | yes |
| outputs/evaluation/fdsn_strong_motion_stationday_campaign_stable10/campaign_event_catalog_screen.csv | analysis_output | yes | 1 | 01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b | yes |
| outputs/evaluation/fdsn_strong_motion_stationday_campaign_extra1h/campaign_report.md | analysis_output | yes | 1623 | e3f4b545bc3fb3efd59c16ed5c6c1472fd6c6a192f1279b803b50c5d9d00326e | yes |
| outputs/evaluation/fdsn_strong_motion_stationday_campaign_extra1h/campaign_stationday_false_alarm_rates.csv | analysis_output | yes | 1578 | f60c2e7a65d812100d138d7e2f0fb3a7f6565b934f9c82ae84fe99500f46145d | yes |
| outputs/evaluation/fdsn_strong_motion_stationday_campaign_extra1h/campaign_network_coincidence_summary.csv | analysis_output | yes | 2206 | 2994917f6bdfa009aac0e930a07a43200a3c96bb02fcd228608b4c83d0d53acb | yes |
| outputs/evaluation/fdsn_strong_motion_stationday_campaign_combined/combined_campaign_report.md | analysis_output | yes | 1391 | 427aa1db73ca053cc257d60af2f085c62f98d678b3dd07610a64bafbd7051509 | yes |
| outputs/evaluation/fdsn_strong_motion_stationday_campaign_combined/combined_stationday_false_alarm_rates.csv | analysis_output | yes | 1623 | 229640ef100af3df69814968fb6843c78fa0081d65aa9feb7b02e3008625d35b | yes |
| outputs/evaluation/fdsn_strong_motion_stationday_campaign_combined/combined_network_coincidence_summary.csv | analysis_output | yes | 2257 | 1781afcad6174cbb696dfc8a504515758becf07de2e0e43c86a656bab6302dd1 | yes |
| outputs/evaluation/fdsn_strong_motion_stationday_campaign_combined/combined_campaign_summary.json | analysis_output | yes | 353 | 1fdb274dac144be865a28a2e71cf4d4ff89a37bbdec279ffddb89826320c7609 | yes |
| outputs/evaluation/network_association/knet_mge4_dle200_network_association_report.md | analysis_output | yes | 15535 | a06b24fb2530433ef5d9eead28f5d9c34289fc6049da01581138ed982706f63c | yes |
| outputs/evaluation/delaunay_association/knet_mge4_dle200_delaunay_association_report.md | analysis_output | yes | 1651 | 1203d706463b97404fdc5959ae52774293df84d1c79aa679662093f4cb3c332c | yes |
| outputs/evaluation/delaunay_association/knet_mge4_dle200_delaunay_association_summary.csv | analysis_output | yes | 667 | 950e9f17daf68416feee4f393656d43eff46caeaec2d81799b2a5f48ad84ef51 | yes |
| outputs/evaluation/delaunay_association/knet_lt4_dle200_delaunay_association_report.md | analysis_output | yes | 1644 | 37d863943f550b36e1347adccfc6e7c6e7786b309dd6aad804fcba42504ff54f | yes |
| outputs/evaluation/delaunay_association/knet_lt4_dle200_delaunay_association_summary.csv | analysis_output | yes | 702 | b4f69aaeac7ad44167e5b2ebed5dfbc80cb3f291ced949860670c9506bd63b0a | yes |
| experiments/redpan_baseline/REDPAN_KNET_REPORT.md | baseline_output | yes | 3483 | ecbf6be55939f9898e629e604c1ed2e0d66420695be5d751eb481d3a211510e1 | conditional |
| outputs/evaluation/prefilled_window_baselines/prefilled_window_both_n1000_mge4_zero_pn0.5_eqtp0.1_summary.json | baseline_output | yes | 1494 | e28382e632839a15926bfa341abaaa1aba73f5dc06e6e6c68070ba153fa5bcb3 | yes |
| outputs/data_audit/strong_motion_verified_data_intake_20260615/dataset_intake_template.csv | data_expansion_output | yes | 2501 | 3ac64f7e6af51aa4d749e1cf1e1aed764fc720298838fedcee6398c1eccee40a | yes |
| outputs/data_audit/strong_motion_verified_data_intake_20260616/README.md | data_expansion_output | yes | 5477 | 22a6a72c496fcdd3fc2f564d54995016beb7816536fa7605ab9c1f8f4130c953 | yes |
| outputs/data_audit/strong_motion_verified_data_intake_20260616/external_source_priority_matrix.csv | data_expansion_output | yes | 4509 | 1b2e0653ab66def78dca08e6dca62375e9bc7b8f47aef55109471bdc1068cf4b | yes |
| outputs/data_audit/strong_motion_verified_data_intake_20260616/domestic_data_request_checklist.md | data_expansion_output | yes | 3273 | 438bd18f17b4e2d784b0dda0401763100f0b68eca73388b6dc3054d501aa2d58 | yes |
| outputs/data_audit/strong_motion_verified_data_intake_20260616/domestic_pilot_candidate_sources.csv | data_expansion_output | yes | 5033 | c10c3b79140b6716a0039e08ec4f55e2cd32eb0eeab5fb40c9efbd1d3cf85239 | yes |
| outputs/data_audit/strong_motion_verified_data_intake_20260616/domestic_pilot_order_note.md | data_expansion_output | yes | 3198 | e6cee30a69080aeb52a27af4cb3d3c075d9f983f8fb667f1d4072593de15f8f5 | yes |
| data/domestic_strong_motion_2021_mge5_pilot/README.md | data_intake_template | yes | 1329 | 017813c2c56861b6cda407da1453ffce18720f62aee7faf4cdcf4cd089c98ba3 | yes |
| data/domestic_strong_motion_2021_mge5_pilot/metadata_template.csv | data_intake_template | yes | 1334 | 90661d1ad0469b75cbcc8fb074aa2f38af670f9a6f49da8369d4c89f4e1f7ecd | yes |
| data/domestic_strong_motion_2021_mge5_pilot/p_reference_template.csv | data_intake_template | yes | 336 | 32777cd30187590ae21dc3cfac77d3507866894bddc1a70b7bb6b51169eb231a | yes |
| scripts/data/validate_domestic_strong_motion_pilot.py | data_expansion_code | yes | 13292 | 9a7f506be95b4565a08bfe8c76c3f0ead36bd3d4931c7b9b7a84d4c880dfe70c | yes |
| outputs/data_audit/domestic_strong_motion_2021_mge5_pilot_intake_20260616/validation_report.md | data_expansion_output | yes | 2680 | 7cb381984f365e999bc6e813b9748719eb908328c9fde91730f15e04c8052f81 | yes |
| outputs/data_audit/domestic_strong_motion_2021_mge5_pilot_intake_20260616/intake_validation_status.csv | data_expansion_output | yes | 1857 | bcf1e10f6f046efafb907323487371cf4dd4bbf3dcf21fdda16f61508a8e6e88 | yes |
| outputs/data_audit/domestic_strong_motion_2021_mge5_pilot_intake_20260616/accepted_record_manifest.csv | data_expansion_output | yes | 1 | 01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b | yes |

## Missing Required Artifacts

_None among the manifest-tracked artifacts._

## Release Freeze Point

For submission, use the supplement archive SHA256 and public repository tag `v0.5-tgrs-submission` as the release freeze points.
