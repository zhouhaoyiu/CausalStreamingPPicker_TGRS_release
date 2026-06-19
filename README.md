# CausalStreamingPPicker TGRS Supplement

This archive is the TGRS supplementary release package for manuscript review and reproducibility checks.

This archive contains the TGRS manuscript, runnable core code, model checkpoint metadata, sample replay data, preflight report, reproducibility manifest, figure sources, PNWAccelerometers labeled-accelerometer checks, and CI/FDSN continuous-stream evidence outputs.

Raw third-party waveform records are not redistributed. Obtain public waveforms from their original providers.

## Manifest

| path | bytes | sha256 |
| --- | ---: | --- |
| `data/knet_accel/metadata.csv` | 2690062 | `797187d0015926b31238586bb5130c7077577281fb1cabf89f10213ab2ec882f` |
| `data/samples/100samples.csv` | 33560 | `973c05e4d79eb74e6cda8c00b0c5e64396b9821d9d4ea58a3d127a72e98eb3e1` |
| `data/samples/100samples.hdf5` | 7571888 | `1ac7024c16f0cd62d4e05c41e9920a8bd5359d10a8c35cd504a3dab419aeec02` |
| `models/checkpoints/multidomain_best.pt` | 1132970 | `4e2dfa897410b77629440602b4e5404479ede7b7459db87ab862cacd7372b51d` |
| `outputs/evaluation/external_labeled_accel_smoke/pnwaccelerometers_theta055_confirm2_firstp_n500_snr20_max320_plocal_m3_summary.txt` | 668 | `f0238a44adf18372dbb0622108754e4a20d352b9c40351cd1483fcae8d2bceb3` |
| `outputs/evaluation/external_labeled_accel_smoke/pnwaccelerometers_theta055_confirm2_firstp_n500_summary.txt` | 563 | `0dc613726b63d843017e1c9baf75983350feb3242568ed7112bedfa938bebc5e` |
| `outputs/evaluation/fdsn_strong_motion_stationday_campaign_stable10/campaign_network_coincidence_summary.csv` | 2215 | `00cc848a7e3dd4d1ae0b3d4179d0996cc37ff55de0d34b9ccba792680cfcee69` |
| `outputs/evaluation/fdsn_strong_motion_stationday_campaign_stable10/campaign_report.md` | 1525 | `71c2bbe324d5ba0899e8d4f21c20e64bed7c8c4f25020f36615ad89807f39fae` |
| `outputs/evaluation/fdsn_strong_motion_stationday_campaign_stable10/campaign_stationday_false_alarm_rates.csv` | 1410 | `26566a34c464d541f4e86371914dfbe943fc51c3917f8deb42a49349056e3828` |
| `outputs/submission/tgrs_preflight_report.md` | 11593 | `4662ced470cbd28f317c93267446650b6107ceba80292f369540a2a98b3b4b09` |
| `outputs/submission/tgrs_reproducibility/TGRS_REPRODUCIBILITY_MANIFEST.md` | 23327 | `dc4accdee1b91e81c55393578d1f1757702c288b9f840371978969f981699078` |
| `outputs/submission/tgrs_reproducibility/TGRS_REPRODUCIBILITY_MANIFEST.tsv` | 22722 | `1e627f8fbfcb16f2508b568287b771dbf8c5443b3f201244d0c55c99a757e3ab` |
| `paper/tgrs/figures/fig0_compute_efficiency_cn.pdf` | 13420 | `c5a56f85b1fdfb8c5fa8a4a6ef6a28c3fc22a521d54d8122caf5b8470734e9c5` |
| `paper/tgrs/figures/fig0_compute_efficiency_en.pdf` | 26135 | `bc4c8b9249c94ae8e47e352304467680dac71ea37be6ee490886505d417a5263` |
| `paper/tgrs/figures/fig1_firstp_latency_cn.pdf` | 15369 | `010bf7a0c4ca88059cf128f6f575843b75c87eb344fc1eec23b3d2b5b8c6971b` |
| `paper/tgrs/figures/fig1_firstp_latency_cn_column.pdf` | 23597 | `7664712ba7e39d5b82aebf2cc97ccf753f65ee968e9ca6cdfdd1f3177b9ac252` |
| `paper/tgrs/figures/fig1_firstp_latency_en.pdf` | 27088 | `78c782d2cdc97a5c9434c1157e3825e0b72fa66e464dcc472a7113fa7e418e77` |
| `paper/tgrs/figures/fig1_firstp_latency_en_column.pdf` | 18802 | `f10f4691de39441812918e679731c4b543e7803d3277f47fa75262b047c3a0e0` |
| `paper/tgrs/figures/fig2_knet_bins_cn.pdf` | 15785 | `cab14c529dff5f10565e4bc45868bf2182ec300c4a75609d79c4d3f62ee40877` |
| `paper/tgrs/figures/fig2_knet_bins_cn_column.pdf` | 45221 | `893e8ad1f192d3f0dd43752a87f3a83caa7a636570393784d08a0fc15ab27d40` |
| `paper/tgrs/figures/fig2_knet_bins_en.pdf` | 28239 | `a38ccd497b52512569b8f7b7daddebc66e0d839fdeb68c3e1475f0644cd14715` |
| `paper/tgrs/figures/fig2_knet_bins_en_column.pdf` | 32119 | `609b244cdafa87be1f87bf7b3a93c942572ac28491d980e5c9ea9defc4da1438` |
| `paper/tgrs/figures/fig3_domain_performance_cn.pdf` | 17703 | `6b4a67291b71cf989911efe0112a488e68bb4af32493709adfe893274c470db0` |
| `paper/tgrs/figures/fig3_domain_performance_cn_column.pdf` | 17888 | `d9b43255f7647b64ee134ca3b1ac9fad17385c509ec5a1f1aef7e7dc24ed05c5` |
| `paper/tgrs/figures/fig3_domain_performance_en.pdf` | 30984 | `4a599ac844054fd1a3250f95bd7553dc8df3af27e22bf92ab08e7aadedc35a08` |
| `paper/tgrs/figures/fig3_domain_performance_en_column.pdf` | 15457 | `c6af4c39d2911af7f8882a7ab832078b89199d806b16aa9934e1ed3998ea4372` |
| `paper/tgrs/figures/fig4_noise_robustness_cn.pdf` | 18855 | `190ac2a6bf6d9abc7395c8297108038f3a6fb179b62e8991db536265032ca88d` |
| `paper/tgrs/figures/fig4_noise_robustness_cn_column.pdf` | 18599 | `5295f6cc33300c4a94b2a7dd9e52288968c8c6550b5c537a74d5467292128a38` |
| `paper/tgrs/figures/fig4_noise_robustness_en.pdf` | 27402 | `3e6a8c7268747706f0be367923752d1c019e0932931ae281f4ea4a02faadd33d` |
| `paper/tgrs/figures/fig4_noise_robustness_en_column.pdf` | 15662 | `7c529d338252a79b9deb927be2def91d166ab16d0d07d92eb2fd316af5628ad5` |
| `paper/tgrs/figures/fig5_subchunk_refinement_cn.pdf` | 15453 | `dacd4746d0b40f7d41d73fc6742b85ce2326a45b2d66bbd37eeab3bffff5c68a` |
| `paper/tgrs/figures/fig5_subchunk_refinement_cn_column.pdf` | 15355 | `e6ae1e31f1b39811105749a62d4c57c769ffd5bcd986c3a70853df517d87a726` |
| `paper/tgrs/figures/fig5_subchunk_refinement_en.pdf` | 29262 | `91602f14ff5bfa240211ffce954d73908252793acbc34e0120679bfa9d32d15b` |
| `paper/tgrs/figures/fig5_subchunk_refinement_en_column.pdf` | 14786 | `636e3c4a49b54f4e2790d2a54f64b3cb2137df623383360eeaf2a71cff874500` |
| `paper/tgrs/figures/fig6_ablation_cn.pdf` | 20290 | `0af31db784ab8cae507376a0904ca8bfeee4b597dba4b6edbb0dc8913b89a595` |
| `paper/tgrs/figures/fig6_ablation_cn_column.pdf` | 19711 | `3eb79fda6149a9dc6c5c1cf287005ddde29979b456edc3c873eb5f3e40175582` |
| `paper/tgrs/figures/fig6_ablation_en.pdf` | 27714 | `11fe044d95599b5c9af85e00e7f63ba83a9e0fd7c9c8826f76e064b32270342e` |
| `paper/tgrs/figures/fig6_ablation_en_column.pdf` | 14372 | `c350aec63d0c992c84e20b61cf1c8ae5e8a0a464c801303102c4ae2a94b74090` |
| `paper/tgrs/figures/fig7_eew_timeline_cn.pdf` | 14860 | `6cadacce1905d060dd354ad50e8dedf65dd1c350d90f646abf5c5750454251ec` |
| `paper/tgrs/figures/fig7_eew_timeline_en.pdf` | 27918 | `2bbe29ca61e3fbc391c7e211b8b5a48c260fc9be21b2b3537195f37bdc701928` |
| `paper/tgrs/figures/fig_architecture_cn.pdf` | 78914 | `e5bb7fe2f001323e317b7d36bb666e19a0ba0904ed9e6e071b727e6034b8a06a` |
| `paper/tgrs/figures/fig_architecture_en.pdf` | 47121 | `094d9b991393259c12da680159c188052a0b90a6ebc414f4fe74d067f90cd380` |
| `paper/tgrs/figures/fig_causal_replay_case_cn.pdf` | 73200 | `52644863e4152bf002b59ed1235b09883bc11f069eb7c568fe3617f1b5e8e1ec` |
| `paper/tgrs/figures/fig_causal_replay_case_en.pdf` | 96242 | `6c48ed5f14430ee0a2f6dc71089a170acb0a8c28afbb880bbdb5d8fca959a653` |
| `paper/tgrs/figures/fig_knet_imperfect_association_cn.pdf` | 85316 | `e1adaac9ffd6a7f33e880903155e5b773f1433ce5a2be118900b77989985dfc3` |
| `paper/tgrs/figures/fig_knet_imperfect_association_en.pdf` | 75022 | `19f76bfa4a91a6b858f80dca3ccdcbe1ffb17d7c8abbbc67abfc7030963e73bc` |
| `paper/tgrs/figures/fig_spike_response_map_cn.pdf` | 71365 | `c57d06408e0eaa97482a6c09dc16197cebd4ba7c28798397644e8c03cbda4149` |
| `paper/tgrs/figures/fig_spike_response_map_en.pdf` | 94330 | `5bbe50e37a8e29fd62c2b1848d0a27083b3d772e1142f6885e463ccd7c991c27` |
| `paper/tgrs/figures/fig_task_positioning_cn.pdf` | 51185 | `0ff1ec4f392caa7bfd72cfe626870e4216ded4279045fc6cca3d0271abb8969e` |
| `paper/tgrs/figures/fig_task_positioning_en.pdf` | 67274 | `110447efb1b75aae80c1173adcf25b8528bda5a3a152ce7efc61bab4c62629be` |
| `paper/tgrs/figures/source_ablation.csv` | 175 | `43109e9f955047008e1067b2e4b45b80d371a09903fb4dd963f0e8497ec6de2d` |
| `paper/tgrs/figures/source_causal_replay_case.csv` | 36355 | `4a2632104e2ad49008db39dcb64a52777780c55c5739b8dc4f824c7b5da0d86e` |
| `paper/tgrs/figures/source_confirmation_operating_metrics.csv` | 591 | `9ba6cf6beeb7b9b552511b38367ecd53bd5f83adf3abc40f958f50f575532a7a` |
| `paper/tgrs/figures/source_domains.csv` | 120 | `b000456af220e5794f3f3c3ca439432e7106472414a2a25b53df5b3e1a78fc0a` |
| `paper/tgrs/figures/source_eew_timeline.csv` | 132 | `37715f1a9b2b886a9abc83c2b80891e771ce3971fa5494ea61d8f93af00f728a` |
| `paper/tgrs/figures/source_efficiency.csv` | 166 | `0964aee4907cc0e15da9b9a32abc54bfc57f9fd9e03df9a09ec293ca112d70c8` |
| `paper/tgrs/figures/source_firstp.csv` | 203 | `b19bfa4d0cb2aa8734d68b2dfa85bb5a7fd12a17d3d5e9699fbc8eea61a6589c` |
| `paper/tgrs/figures/source_knet_association_operating_point.csv` | 1036 | `d72fa67fe9829155a30d0c0827a348f38363bb433a39f6d6d0babc54b31808cd` |
| `paper/tgrs/figures/source_knet_by_distance.csv` | 184 | `bec94960335dea3b2712682120e11fe9c4c8b4139e012f8d8a4819c218753d86` |
| `paper/tgrs/figures/source_knet_by_magnitude.csv` | 154 | `4f5c6cff1c636d07b47d04123babf74cea651450feb11af0400e59803aa88b29` |
| `paper/tgrs/figures/source_knet_categories.csv` | 129 | `7be21e8531c8a5a9f042a5d27ac8a6f45c827c5fa9bf8f2b7377030dcac9942e` |
| `paper/tgrs/figures/source_knet_stratified_detailed_metrics.csv` | 1359 | `d50893bfb3ba0b2c5ebb71eaa09cd47e72aeb438a9e0197bd51d9fb7120ad1d0` |
| `paper/tgrs/figures/source_latency_complexity.csv` | 597 | `05da434ff0f530349d3ad0f59ad0ab5fa3a2e107dbc85b2d0ea0ca42e80052e3` |
| `paper/tgrs/figures/source_noise.csv` | 246 | `6435ce1b742be48d9a6881e6212a4357b55b91667d8ca50920e34d78d98259b2` |
| `paper/tgrs/figures/source_redpan_knet_comparison.csv` | 481 | `2da6f57aa02db9343c22e226f3ce070762fe5708f1c9c3305fbbc2457d5bff19` |
| `paper/tgrs/figures/source_spike_false_alarm_stress.csv` | 1700 | `49047fcba61b948557c72e1a8f800184a6e754c6739e157bd41bd30284e9537e` |
| `paper/tgrs/figures/source_spike_response_map.csv` | 1940190 | `e4355e7c699f4aaafd1f97f70cf8e8cbbece1b4a9eabb396a1155a3ef7c4458e` |
| `paper/tgrs/figures/source_station_detailed_metrics.csv` | 1733 | `e1c51a5aaa14e9e0fdb2390a876501d625b6c9001b9267a557222d836db9430a` |
| `paper/tgrs/figures/source_subchunk.csv` | 174 | `6c01478c6c2ae902af2842abc938336db19ebd792e8af47e7032f217e4cc0276` |
| `paper/tgrs/figures/table_continuous_false_alarm_en.tex` | 1353 | `e082a84ec1fc73bad4a80aa1889f93b81836254a81408183478947f3530d0b4d` |
| `paper/tgrs/figures/table_fdsn_continuous_false_alarm_en.tex` | 1064 | `c3223ac8393b894377c1033a746b4651f81530cc25ee5356f477cf7866a0ce6f` |
| `paper/tgrs/figures/table_knet_stratified_detailed_en.tex` | 1199 | `81dd11b52786fd656fe099279695747d2acd3dee6294fec0027b09e0962e44c1` |
| `paper/tgrs/figures/table_spike_false_alarm_en.tex` | 777 | `4cc58fe825f84d1cd45a12525ae997e6bfb7d54713068788bd7f66d4b3c3f4ba` |
| `paper/tgrs/figures/table_station_detailed_metrics_en.tex` | 1611 | `09db4acb12970d14a70e5e6682fb9a6920c212fcf98d5f026f15a19b691b6f7a` |
| `paper/tgrs/figures/table_stead_noise_false_alarm_en.tex` | 802 | `138725e98370d1257b85b71c072faec1744946fccd3c69dff1aa1e4d16b57cf3` |
| `paper/tgrs/references.bib` | 29084 | `980d12198e6dff68ce33cc444faac6e838ce97bb03d5db0c2ba4072367b38963` |
| `paper/tgrs/reproducibility/CITATION.cff` | 938 | `1911a837c5b1e5eef0b94a00b885fcedff922a9551f81315d5895a0b3db42900` |
| `paper/tgrs/reproducibility/LICENSE` | 1067 | `a083074bc5725255331d5cf80691ca44145da891af2da54fb4e5eb50e006dfbc` |
| `paper/tgrs/reproducibility/MODEL_LICENSE` | 494 | `eec62a1786a92f6307e71432f1d9be659caa9cde791c133dcda760a57a09321c` |
| `paper/tgrs/reproducibility/README.md` | 639 | `8d47a2d8129ee77f06ad6da5b01d69a5c7b7d9727bf77c86a250aa2de4d52b7d` |
| `paper/tgrs/tgrs_causal_streaming_picker.pdf` | 704783 | `c325f865a95a39a35afd28cb8e26ce1bbd634af16875477ce8a1b55cda41c878` |
| `paper/tgrs/tgrs_causal_streaming_picker.tex` | 61032 | `6ca894b94c663b81ea9c5a92cab3cc39fdb96f6b3cbbee05133425dc853b6438` |
| `requirements.txt` | 165 | `7479922b77e1b4ebec8c4199c5fb8c181c1d2de77fd1b2bd1cf796ae0e6b9c25` |
| `scripts/evaluation/eval_compute_efficiency.py` | 34971 | `5b9eeebe01591082f0ebaeeca25e08886b8a20f0d7c5070c5b4599907b7df9d4` |
| `scripts/evaluation/eval_cwa_tsmip_external.py` | 14631 | `ff320c673e5bf0b1db4fbb28805dedceeffa425c66d47d63d5107a86b1c35d64` |
| `scripts/evaluation/eval_fdsn_strong_motion_stationday_false_alarm.py` | 34856 | `5cc1f1f21c36031824a618232c455e2dc412eb73379bbdce9614140e1cb4b683` |
| `scripts/evaluation/eval_first_p_delay_cdf.py` | 45984 | `6520089a13e122b10b40e1e648f59c3d4e4059cf31a462d2282fdaeacd205be7` |
| `scripts/evaluation/eval_multidomain_test.py` | 23355 | `b1782e9918a5d68450e5038d7bcaee21d4add0043f5b4b554b648d565fe97dd9` |
| `scripts/evaluation/eval_spike_false_alarm_stress.py` | 18128 | `efb3c37ebed155425f8733b858fa7c6f5d0fe7e4b1cc0f52e940d12e8ac06823` |
| `scripts/evaluation/run_fdsn_strong_motion_stationday_campaign.py` | 11210 | `947368f1cd0dbd6a1ec38fbbecf0052fa776807e1356f15a71118f454ed5c366` |
| `src/config.py` | 634 | `7c9be2490ff6f976fb79c50bbca213c1915fe775258cfab167af33114b1f534e` |
| `src/data_streaming.py` | 8477 | `f043e676840011a480a02385ac60758fccd1e652c8720015c92221405d18abe3` |
| `src/knet_dataset.py` | 7762 | `5877b6b21e8924ba51ee4a1c749bd921e20367181798e79dfaf183e50741a8d1` |
| `src/model.py` | 184 | `f0dc6a04b603f0ce23e4ef1d9124411cce1c3508d6a379d73ebefc619eec046c` |
| `src/model_impl.py` | 11534 | `1bc4c632b9526b1e00269c89e50b93b2e55747ccf5aa3f29e7b9d87cb70de0db` |
| `src/project_paths.py` | 789 | `b395f1f3ce51e5bb321e8d1faf3f75ae25da1a8c55493a6bbb020bf353a10276` |
