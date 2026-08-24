# Reference Source Baseline

Generated: 2026-08-24T04:51:43Z
Harness: LONG PROJECT crypto-auto-trading-system
Rule: reference sources are READ-ONLY. Before/after comparison must be identical.

## 1. SilverQuant

- Local path: `/Users/huhongjie/Downloads/SilverQuant-main`
- Git repository: NO (source archive checkout)
- Source identity: SilverQuant-main (downloaded archive, no .git metadata)
- URL: unavailable locally (archive); project: SilverQuant
- Branch: N/A
- HEAD commit SHA: N/A (not a git repository)

### Pre-existing status
```
not a git repository; no git status available
```

### Key file SHA-256 (read-only baseline)
- `backend/app/core/contracts.py`: `b5db7c027e575a97ddd5f3d3a3723734131a7fcc94ed3bf335d123a5c4c76fd1`
- `backend/app/core/gateway.py`: `3773ac0591456ecba9610a10d331ddcd7b62b7551df383d2e998aaa3aa902bb5`
- `backend/app/core/clock.py`: `b89baf6183464c049f5cfc95dc114d3ab9bc7027631aaa321e491e6757a455d5`
- `backend/app/core/paper_broker.py`: `08e3d16cf293b75368284d052770c8e85db4129f7701e2da1ac6d643c5d2b336`
- `backend/app/data/sources/base.py`: `9eb87bd86a91d506d5d12b00a34b1c13f095f184a566959c160d161636f45457`
- `backend/app/data/providers.py`: `8fb2d0a9f5cde87f3cbd57f77c93a45b47b52e94fca474afa9057edc5c7214c7`
- `backend/app/order/manager.py`: `63e938a94dc687dd2fec3899fc43f0ddbf5d9f73d849fb5b37d4739c8b69acd6`
### Directory `backend/app/portfolio`
- `backend/app/portfolio/__init__.py`: `c29b76de7b7390f0f23b2951c62a1b8fb0df8441c3a03afc4119cf34279d25b6`
- `backend/app/portfolio/portfolio_state.py`: `61a990c1cbbec76278ce873e230faaf9acbcb217c23b4590b9fb478b862b401c`
### Directory `backend/app/risk`
- `backend/app/risk/__init__.py`: `74656d646c2aa2c35f3aea1d77b379db93fe7141df0a2efed10f287539eedff3`
- `backend/app/risk/guard.py`: `26044f2d26853f1a383edffdc181ad8524beec451d1633628c18dbe8c62ba168`
### Directory `backend/app/orchestrator`
- `backend/app/orchestrator/__init__.py`: `2a65f600ebf47c4e1ca680ed232d5ab688a9c0dc2e21567517702dadab6ac08c`
- `backend/app/orchestrator/live_loop.py`: `7266a4be426d5b581ebac3b3a8af63a142c25d2cce2ca80359def6d0607215ca`
- `backend/app/orchestrator/orchestrator.py`: `35e05f2c1cb297ecaa57ce00774fc0c860df0a4ed6f0c4497d341f68db2be20f`
### Directory `backend/app/backtest`
- `backend/app/backtest/__init__.py`: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `backend/app/backtest/contracts.py`: `ecabb6b7d2560c4e61202235aef160b6fd88957cc0d627d58e51b7310f4e0df9`
- `backend/app/backtest/engine.py`: `464a0cc292810f6261548fe8266cb1a69c8a54cbae1d8bc724e22bb51c3e63a5`
- `backend/app/backtest/feeds.py`: `c1dbd9e94b7c37fb66caae17dd39ef58f2d52c5a7fb0e6b368c0521e103b95b6`
- `backend/app/backtest/matcher.py`: `ab73ae26429c39bc1332f18a9f2f9a422201df297b45feb5a02688a1d2ee6fd9`
- `backend/app/backtest/portfolio.py`: `78d6b00840725dfd1ba0b23d42d12bfbe08237aa7f7e11c5a1b0d68481747dd4`
- `backend/app/backtest/report.py`: `67bdfffe0c1954d08657865b1ac6b179ebe7109cf7673dd0b6a922116602404a`
- `backend/app/backtest/risk_guard.py`: `e3382c78470038c4a33255bb33257e09a44b90016a43813b2f1aaa2bf3a9d28d`
- `backend/app/backtest/synth_data.py`: `46d91cb4ae44b1e770ce36f5465db82d996b206aff9349da47fe91c53ef94cd8`
- `backend/app/services/audit.py`: `3eebd01dffa2474f807b83eef763922a26e8c490d5b0209f102b114154036e0f`
- `backend/app/services/trace_db_store.py`: `b899ad65e10c2cc81f55036701a5315459b0e2ffb4857afc808f70f7ced1001e`
- `backend/app/review/replay.py`: `609af8d79c353432b132d2afc8f0d1ef7785a60837eb31e07ed9db92c6aa6602`

### Full file tree + aggregate manifest

```
209d1ed5fd4e083fe5815cd46063be27fe385be042f38d6645ff516c7ac3f619  ./.env.example
badbefed4d111eee7df88f5126434bc334ba977088cc92409e57fc97f68cd759  ./.gitignore
304e573bb8d54df8ffc909e315021e8ab0971ec68e1854923c00940ea07afff5  ./README.md
ac85450bd2679b1b1d02c461ceb6dd44fb4f5d3ae79945af05ef2dcbdb1ae1a9  ./backend/.dockerignore
64b641e2981a3a9c844b0a85f1f38bd028c3bfdbb315c31b27c5f42f99903d07  ./backend/.env.example
0447ec6b9b79a2c2d139c11b918b0c4eb439bd248bde518af38f919734552c18  ./backend/.env.production.example
8f641300733ebf69c429778dd15752fcacb98913ad8d4c49c8c680f7ff707ae1  ./backend/Dockerfile.backend
8f02b86d7ff132b00a8e49a8a849a0bd82c7b657b0a04a56c94ce9c21cae57d8  ./backend/app/__init__.py
410312a3e18d95913e11a5d2a643bc8d1fb440a653b46f2be061231d599bd950  ./backend/app/accounts/__init__.py
d68017d2f4e07ee6ed0397a91ba0c0401f49ee9e74e15fd693c769e9a52bdd94  ./backend/app/accounts/base.py
7b36db764eda879f5bcdb082e10229fee8f94493af71edeaddd57864fa517afe  ./backend/app/accounts/sim_account.py
5fce0797a0687229370660c8630f1d083c3166ce07707959ed3eced5259356c7  ./backend/app/ai/__init__.py
57e1ecc36c72db793baf6424b873fdfae38b13b80aa8bec423425fba743ee500  ./backend/app/ai/provider.py
7b3fa1c8e46ae59ce8d2d980dbccf0166f173f274e7a4a3ee6fbe0d356d2fda8  ./backend/app/ai/reviewer.py
581c798d192bfb0fd0563b8483e3a2c2ad1a5555bca8c7322f2148e36e556677  ./backend/app/ai/verdict_cache.py
2f6210bbca5b9dc89deb63fb23ce649d55124f125703e859931a0b82eb06cfc4  ./backend/app/ai/verdict_store.py
f4ce5d8d29d4cb8d8426c5fd326fc62ced47b2bb2a684e17dc35faa95470ca77  ./backend/app/app_factory.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  ./backend/app/backtest/__init__.py
ecabb6b7d2560c4e61202235aef160b6fd88957cc0d627d58e51b7310f4e0df9  ./backend/app/backtest/contracts.py
464a0cc292810f6261548fe8266cb1a69c8a54cbae1d8bc724e22bb51c3e63a5  ./backend/app/backtest/engine.py
c1dbd9e94b7c37fb66caae17dd39ef58f2d52c5a7fb0e6b368c0521e103b95b6  ./backend/app/backtest/feeds.py
ab73ae26429c39bc1332f18a9f2f9a422201df297b45feb5a02688a1d2ee6fd9  ./backend/app/backtest/matcher.py
78d6b00840725dfd1ba0b23d42d12bfbe08237aa7f7e11c5a1b0d68481747dd4  ./backend/app/backtest/portfolio.py
67bdfffe0c1954d08657865b1ac6b179ebe7109cf7673dd0b6a922116602404a  ./backend/app/backtest/report.py
e3382c78470038c4a33255bb33257e09a44b90016a43813b2f1aaa2bf3a9d28d  ./backend/app/backtest/risk_guard.py
46d91cb4ae44b1e770ce36f5465db82d996b206aff9349da47fe91c53ef94cd8  ./backend/app/backtest/synth_data.py
da827ff389f52df7cda4f74bd1186e56ea6083d43b1f645b6834199718ac4611  ./backend/app/cache.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  ./backend/app/config/__init__.py
7e61dc9e728ae319b3a308efa8eb39a186bdf491308407d05b8f35999a8f3b54  ./backend/app/config/database.py
9c521b989bc4d52022514ed6eef60b8fdbf2a3c5ce58a15a45af94265c43a9ce  ./backend/app/config/settings.py
1b9a01a2de8f077485434b1d613b92a5b84af37e7e82a01697beacb5bfbfbf88  ./backend/app/copilot/__init__.py
fee423f15c49ecf4fa7759155d957b95cf6bb49ddceaef2d5b5869ab1c229307  ./backend/app/copilot/llm_client.py
24c0d8736a89c73f200d69e11aa9e577e4e1818f630810d7bb55acfae15a663e  ./backend/app/copilot/prompts.py
508707bc536ce66b8b06165c6e555d23ffb1ecd10b881247bcbcbb504c61ad1d  ./backend/app/copilot/proposal_store.py
75306ddd02819ba273a34b65a5d32e8004eb897dcb2911c49114faacd1c16182  ./backend/app/copilot/service.py
81f2f5508c20f3637e2e5c66e88befaa914fd52d06e4ad5d78c0103a37f2adf3  ./backend/app/copilot/session_store.py
4fd5b2b9db95d070c2fcfe786b1396a8cba46125dd4659fb65f1f72cd10431ab  ./backend/app/copilot/tools.py
cd20886eb074b0ec65886c0aded6035a9dcf9db3369bb431ef90a2c8edbcf944  ./backend/app/copilot/user_manual_kb.py
04b1c53ab9149216fbab0e218da98acdd9e135d1f32ced3290916629834e3722  ./backend/app/core/__init__.py
b89baf6183464c049f5cfc95dc114d3ab9bc7027631aaa321e491e6757a455d5  ./backend/app/core/clock.py
b5db7c027e575a97ddd5f3d3a3723734131a7fcc94ed3bf335d123a5c4c76fd1  ./backend/app/core/contracts.py
11bd270b3d6554a64a17d976b4d3b6b3def6c3785011407dc6d22987b4f3e746  ./backend/app/core/feeds.py
3773ac0591456ecba9610a10d331ddcd7b62b7551df383d2e998aaa3aa902bb5  ./backend/app/core/gateway.py
a5678d63325fa2ac7d159fdac2a2f1f4d1708bc778a37dad6208d6af0812fd6a  ./backend/app/core/live_trading.py
08e3d16cf293b75368284d052770c8e85db4129f7701e2da1ac6d643c5d2b336  ./backend/app/core/paper_broker.py
889bafaff4a5e82401efbef65daaefcd28403faab6308e0aa5c3629646e1c6bd  ./backend/app/core/provider_feed.py
1769c21f70af23e91f6522ee10c7e41520950ee62ad90caecdef13c8491526ee  ./backend/app/core/runtime_params.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  ./backend/app/data/__init__.py
368dcde9c4006c5015b29ff416a017ef0537e5d5e3c68dc11bb8b49f1f6f53f3  ./backend/app/data/astock/__init__.py
66295e93eb4e83d63b3137b476f8b949050ee4dc49b68102d316a4ea23741942  ./backend/app/data/astock/extended.py
54c008125b0f4e4fab00ea5e9fdc418b26384c5bc47e2e83ae27aa2da9393d31  ./backend/app/data/astock/sdk_loader.py
1fa779e644ff0a1a4f2a1fd342f32cffb80e277cf6fd769fc05341709be04b7e  ./backend/app/data/errors.py
dda6e9cabff6fe7d101630ee3bde025e4bbdf20611b54ab77f6de639f8ac1816  ./backend/app/data/feeds/__init__.py
add45d2a25c125b8136f6aea55a51f063d05aaac71174c96e7502628af3e54ba  ./backend/app/data/feeds/historical_replay.py
8fb2d0a9f5cde87f3cbd57f77c93a45b47b52e94fca474afa9057edc5c7214c7  ./backend/app/data/providers.py
12ae32cb1ec02d01eda3581b127c1fee3b0dc53572ed6baf239721a03d82e126  ./backend/app/data/sources/__init__.py
d02b74c85d2bea2278754db8fd4ebb676870436f1c74f15c3d12dccee153bb3b  ./backend/app/data/sources/astock_source.py
9eb87bd86a91d506d5d12b00a34b1c13f095f184a566959c160d161636f45457  ./backend/app/data/sources/base.py
abecf8e976fb1f9e890090ec6b7dc51613f4c3d2ec2ef98ba4a098e732f14132  ./backend/app/data/sources/eastmoney.py
38ea24219ff2e1b9beb0d8047af8cc10307ce108ed601a2a1cc6f6d5c8107a99  ./backend/app/data/sources/tencent.py
650f1a3289a499639620a0ebd34f7035d3e44943656977f297d1d8fba4b2987e  ./backend/app/data/sources/tushare_source.py
8b084a9f378124b2b1a51563bf3c22444eb7ff33692017da28b2136ae56987ed  ./backend/app/maintenance/__init__.py
cbbecebfd51b131f4b854425649f98fd3ee8ef44e390f4e02d5d5799816f45ac  ./backend/app/maintenance/factory_reset.py
2a65f600ebf47c4e1ca680ed232d5ab688a9c0dc2e21567517702dadab6ac08c  ./backend/app/orchestrator/__init__.py
7266a4be426d5b581ebac3b3a8af63a142c25d2cce2ca80359def6d0607215ca  ./backend/app/orchestrator/live_loop.py
35e05f2c1cb297ecaa57ce00774fc0c860df0a4ed6f0c4497d341f68db2be20f  ./backend/app/orchestrator/orchestrator.py
b3e6b26e1cc1792b2f14578aac45437bf6e9b5050de7d078378c5d22c3120406  ./backend/app/order/__init__.py
63e938a94dc687dd2fec3899fc43f0ddbf5d9f73d849fb5b37d4739c8b69acd6  ./backend/app/order/manager.py
c29b76de7b7390f0f23b2951c62a1b8fb0df8441c3a03afc4119cf34279d25b6  ./backend/app/portfolio/__init__.py
61a990c1cbbec76278ce873e230faaf9acbcb217c23b4590b9fb478b862b401c  ./backend/app/portfolio/portfolio_state.py
f5f13b35e25c286f51ee91441deb285eeda7d555e19b2173ab7bd7ab14534437  ./backend/app/review/__init__.py
c3450fdf6d2f39968efbf4813006265dd42ca57f6e3c38920980e2cd444349fa  ./backend/app/review/performance.py
609af8d79c353432b132d2afc8f0d1ef7785a60837eb31e07ed9db92c6aa6602  ./backend/app/review/replay.py
6194f2f79193d808c7626debdce128850666fd1791b599ddc030c005a6ea9c3e  ./backend/app/review/trace_service.py
74656d646c2aa2c35f3aea1d77b379db93fe7141df0a2efed10f287539eedff3  ./backend/app/risk/__init__.py
26044f2d26853f1a383edffdc181ad8524beec451d1633628c18dbe8c62ba168  ./backend/app/risk/guard.py
12ae32cb1ec02d01eda3581b127c1fee3b0dc53572ed6baf239721a03d82e126  ./backend/app/routes/__init__.py
db00ed8f29357db62e1bdab96c114c2ae32e78e063dc7d39305f7a6a54b80cce  ./backend/app/routes/account.py
6da4773804645753dfa4abb96f8695e55f666b31fedf355e501b2dabc8659c38  ./backend/app/routes/ai_config.py
2f7271ff0ac9385848956c14c4e61fda6d2bf383399f3b7377bd1ba8276fca53  ./backend/app/routes/auth.py
158dd4e20d30b9fe3e2790ac37a8eeda0a606968d48681094999fec58051ce24  ./backend/app/routes/bot.py
ff1cf7abee68c2ae5c16d84ad3ccaf71daf348ed4a95bea9f5b05fc8a435ade2  ./backend/app/routes/copilot.py
c2705a1173dcc33579828eb409b24d11d3d4f60b79df9e533f6ce05a08eeb80b  ./backend/app/routes/custom_rules.py
f4822ddd2582544ef7b6ba10b6c2659b16479fa6e61fdd90b9b266d2e468e890  ./backend/app/routes/health.py
f417f60ecc37a964f432c1baa3393aeba210b6b57fc4339c02a09caa3103aebc  ./backend/app/routes/market_data.py
fdbad0ceb00d092768037f26ed013e80c51e476a91fab1de513d9af0e0f64c59  ./backend/app/routes/order.py
756f8716a504387457a63f85fbc2ef3b8fc00982492331e040ee330ef528a3d7  ./backend/app/routes/params.py
cf3d2e9d8740b313c574ad04150ebc6d5eec30e29437023879aabda753424c0f  ./backend/app/routes/simulate.py
7ed9f0eaf179648d4daae1c2b4317a301aa30b25db05ac576d617784566eb378  ./backend/app/routes/strategy.py
020f35a2c341c3769c561498b00fbb7cb477b958b58f0563899dc917898cd910  ./backend/app/routes/trace.py
f9d80f5bc95c1471589b83f9678c5d3c1b3ead43615a4118eb6af27089e7f8a0  ./backend/app/scripts/run_retention_purge.py
f07cbe1e2fc63fda0193eeafe4bff04076c0149f35aca05a9807650ef5859001  ./backend/app/services/ai_config_store.py
394bab0618179a3a9ef30c2078fcb31600c2f20c7ad7ba766a5fb940a28e559a  ./backend/app/services/ai_runtime.py
3eebd01dffa2474f807b83eef763922a26e8c490d5b0209f102b114154036e0f  ./backend/app/services/audit.py
5a2e84bfb1445d7d6739b0fde187ef7cc86eff43d20d4dbc0329a9c694a5c70c  ./backend/app/services/bot_config_store.py
3203ec25432861108ff05fe1f24180d1b137aaf60d1c7eee91831bb8aaa90237  ./backend/app/services/data_retention.py
cdc4b3329a83510ad12d58e88ce7e558d38b4b3bcfadd7db1553a86f29d3b624  ./backend/app/services/dynamic_rule_store.py
bdfbcc55aa58ba954819a8b3d9543b6f686ceab358d9c70259b1493759d58c1c  ./backend/app/services/orderbook_store.py
3b5f3c1a452d4f19d27b07154e9ff3fac94695a226a0d8dbefeade408c22c5a8  ./backend/app/services/param_store.py
eab82a185551bfecec2e5c57babd0f2ad72e23ac6a89195a04a0ff98b5d5222b  ./backend/app/services/position_store.py
df0704878794b07851ccd6344d059b14e8059e5d653c8000b357032cb184f2b9  ./backend/app/services/retention_utils.py
b899ad65e10c2cc81f55036701a5315459b0e2ffb4857afc808f70f7ced1001e  ./backend/app/services/trace_db_store.py
b247d2e1f7d176460886b8583c4f30f0d2e3bc038a030cba4f095827d01fd1cf  ./backend/app/strategy/__init__.py
bc6a144f62f2de3f3a9ba417618fb36582a55e9549023dc1dc96331134e2e50b  ./backend/app/strategy/candidate_pipeline.py
381f799b9ed2ac8dd956f68e2659aa72103177aa9ed872088bde69533abee6db  ./backend/app/strategy/decision_engine.py
ebcd8d0cfeb4868b541677fd2b59dce1719258d5394ba7eda27532c4d336b9f9  ./backend/app/strategy/dynamic_rule_plugin.py
806c505fe8c89acd97869032a299fd36d352b0af11f68d507fa531bb22eb20c3  ./backend/app/strategy/limit_price.py
45c661f555b048140b127872e8050565b2dec76fb849fa42aa5e20cfa617f739  ./backend/app/strategy/orderbook_signals.py
93df0cb69a9103dd511d2aa8105800a3b1e79276aa7f254a237af203ffe37bca  ./backend/app/strategy/pool_scan.py
31ec483de32a019f92aa892b8080143b3adbab29388f8596c42cbe12a60cc3ec  ./backend/app/strategy/pool_selector.py
3c73adc7877bc18a61a4d44440603e6177a90fdce03dc222229d547a1d4fb7f9  ./backend/app/strategy/rule_atoms.py
62ba4cfaf2ff02cc4e236fa786bb700e90123a536cc9ade16ef3e75df0258bfb  ./backend/app/strategy/rule_contract.py
89ed8f62ce4cad8efc44c536ff94486c1489f75a18630324d58455a5aea1c925  ./backend/app/strategy/rule_copilot_api.py
352972643476996a5d1e6f329d9aa8e748f7e680e57360f8fe02bb4b14123949  ./backend/app/strategy/rule_dsl.py
fd32e08645c49ff72b2763882235dc24d6ebf43f08c182bbb433799559f66c85  ./backend/app/strategy/rule_dsl_simulate.py
41d69901858ac3105352d8a14addc16df04e59da45f1db5772668278b369833e  ./backend/app/strategy/rule_engine_factory.py
007cce81a98660cdc5ee5d8dc8c9688e42e520f5da4a44cd703006bf687c1b56  ./backend/app/strategy/rule_indicators.py
565f7e6d8669517ae1c2000d774dcb09e75ffe7033741628ce087c39f4b603ca  ./backend/app/strategy/rule_orchestrator.py
8a3d0c50ace17d71beb1d619fe36375c5b90af9212aa46aa8461b6ca4e93c865  ./backend/app/strategy/rule_presets.py
a04f3868e331dc7b2d4e7bb4ff1c954f40df59db1669539359d1e9ca5d5b67d6  ./backend/app/strategy/rule_preview.py
3b23cb85faf9d2ef532377ba5f80de9e22c363108d09cf286d275e7ebcfe8db4  ./backend/app/strategy/rule_reasons.py
29ef4388d18d4f2aa83dbb0bcbb9b37074f02d47699f33ae31fcbf9a4173f627  ./backend/app/strategy/rule_registry.py
0cc8470ac848b8375c5f2450921957872d168eff50a027678665d895f5f4cc17  ./backend/app/strategy/rule_templates.py
0c6c0edf2d6fc8ff122ebd8b16594b8ae723c70bb04cebcaf6799183ddfe748c  ./backend/app/strategy/rule_validator.py
28b0605364c562677c061545a51b84a9b0c99cc7dfc36d876667bf0dcde478ae  ./backend/app/strategy/rules.py
32b3a7ffb9a700d0f3725016607f7c6b0e575e4f2969229ff62f50c5524b7a75  ./backend/app/strategy/rules_plugins/__init__.py
32088e6f10cde392ac3d2494bfec8dfae899e50b19f0113b57ff33e0e61e9ab8  ./backend/app/strategy/rules_plugins/rule10_stop_profit.py
3e0c72d9ca9237fe300a9d720dffe9b00d22774996547b1682db7a25dff0737e  ./backend/app/strategy/rules_plugins/rule3_macd.py
e605bf408dd301d4b6d6a7efb42ecc7f535c35115605f714106534eef9473559  ./backend/app/strategy/rules_plugins/rule4_vwap_support.py
aaa22fd710be6bbd10c60fdeabd360934b3401e1dd92489d40ff24a321e785ac  ./backend/app/strategy/rules_plugins/rule5_panic_l2.py
38d3913121c73c7c39d1ca5056ddfb2b14a2f392f785be199b2e97820743cd2f  ./backend/app/strategy/rules_plugins/rule6_t0_profit.py
4612c52d9260d661d079911df97a6a9be4b1fa01fa41d81f6aa51dfc1eab4932  ./backend/app/strategy/rules_plugins/rule7_fast_rally.py
01520f1cef74c86f5ad3a5831e0132e65e14d4d4ca501e5a9932bbedc138e1ba  ./backend/app/strategy/rules_plugins/rule7_rebuy.py
b94a2f4c731d79c2e0b7311402d63b4d10139cbc352f6d68e0b640b00427fad1  ./backend/app/strategy/rules_plugins/rule9_limit_break.py
608ad84f341bc72d0f79d6376a9b72f027a3b42ec9fda456d4787a34f154de84  ./backend/app/strategy/weight_enrichers.py
aba0aa2b1070e628f3a80e581df32685398ba3f8fd62570b67fed0518a92c448  ./backend/app/strategy/weight_score.py
e6685989ccd3400efcfe44c28a69cfaa2309e632bd86492f79b7208785428d53  ./backend/requirements.txt
e462d35f16f33875f002a2409da394e362f8cab685c316908bf3af6b498edc16  ./backend/run_tests.py
5241fdf9a93160a1fc9b37730a34362610ef0e78b6dfa00f45fa218463ffa3f7  ./backend/scripts/fix_rule_names_utf8.py
f2669f8b4432065d6518a84f58f72ffda8c2e09f5cae18ab26a9a7410cb94e35  ./backend/scripts/reset_factory_state.py
2dc642b83a1a47e5b7e63383b675bb5e0fa3c6da4c836e4affb5a3fa4955af82  ./backend/scripts/verify_registry_copilot.py
12ae32cb1ec02d01eda3581b127c1fee3b0dc53572ed6baf239721a03d82e126  ./backend/tests/__init__.py
c395d062997e6f6323c72c3ae32d1cb03958428eeb931810d0db06d185fcf4f1  ./backend/tests/integration_harness.py
64d4753a55d4a010812edce679ebaaa22fede8103d1b01c9f5d685f3d5d807c4  ./backend/tests/run_scenario_audit.py
049c47092cbda5848f6dc0424d4599a0a2ba8ebfdbd1b027fc58850d7adb6e72  ./backend/tests/scenarios/manifest.json
5376aa95c88bada4d4b0a2499b89a01d615132cfe84b8a050538d7f94be6e67f  ./backend/tests/scenarios/s01_synth.json
31e5a416a883887e79e7baef3de222408ddaa6e40b0f26c5b861f146aa17b9e4  ./backend/tests/scenarios/s02_limit_up.json
fcd4c046ce867269bfca9b14b583c7c1a54b80c85ae6a50e6a4a604295f8c287  ./backend/tests/scenarios/s03_limit_down.json
7d1fef90f55248fd315e3cfc8fded528166475f16f1371bf6a77d6d8e1af0492  ./backend/tests/scenarios/s04_t1_block.json
016612b0463bbe7a0405e47b7bb714b5e4a8474a39d9462fe414e3b016788440  ./backend/tests/scenarios/s05_t1_settle.json
9b8174cd81b1405367128843a74c0d36e2b68bc6ca4cccd280baa4368e588957  ./backend/tests/smoke_bot.py
417af77f8d0f6059190cd79e6267f01250abe4fa61b0b84290420e53a5d5e7d9  ./backend/tests/test_ai_config.py
54f9c4b3d87983c041e0617df1cc3f781a606e3a39ddc0460635b4de62ad8429  ./backend/tests/test_ai_rank_pool.py
84134d281387d1c75c80207687a4be33b37560ac77b9f7aa1fc323a245672253  ./backend/tests/test_astock_integration.py
904b40afa9fd6ca6dbc8d2a7277d74575ea8deba8cba64731f364f5157eab1dd  ./backend/tests/test_backtest.py
bae1f9cf5e504189fbd74099d3c5e4d14cfc6ed1477b116c9e415c205fd0accb  ./backend/tests/test_candidate_pipeline.py
57e6e9b059dff18741674c9c4c5d1d421d8a43cc9fa50805574c6f1551ca633b  ./backend/tests/test_config.py
8196926654fa0dbda021a6ccf1772dc18d71224ffa1cff3c51b0b4c5b558bbf9  ./backend/tests/test_consolidate_hits.py
d895531d0f37e176dc513df32428a96d241219f19d6c8d7731a456fdcea5c485  ./backend/tests/test_copilot.py
e90bf858761023613e4745596dcfa8bcb6facc24f6a4d4fbf8647c8cf22ab459  ./backend/tests/test_custom_rules_api.py
83e008b2b7f9d26d26274ec74d45370058b743a6c4b9227a20f1cfbde7d34c72  ./backend/tests/test_data.py
404113fcff591b94ac15f5b9197fbfa6f2712d340176138dfdc130c2fd53b2c2  ./backend/tests/test_data_retention.py
31c9caf27f4e1a6b9206d8e6e81465c37c522843435ded893748af2c8f2e7ba4  ./backend/tests/test_factory_reset_api.py
e0927c97886eb35a0de1a0c0e01049d18f15bf8fb97f9729f4586a884fa5d522  ./backend/tests/test_factory_reset_trace_memory.py
3dc383488dfc34c520340d32e499344559af2a60f2718d9bce9f1fa8e05144fa  ./backend/tests/test_health.py
e473bb0fc38f7832c55fe9152ddbba665e46d8c2b0e6cfde5a23833b3b511b73  ./backend/tests/test_live_trading.py
74eac540e0d692c762db99f7289c5820d437a68727386b92e296d134ad03c35b  ./backend/tests/test_m0r.py
bdd357e6ef6b0882e390bcf155935b71472f0f32f7de7fbd4380f39d6275356c  ./backend/tests/test_m1.py
5a7e8233b1f1b84a110477c6c1ab6d57e43a10e02cba7c2714dfbd2e2a8ba440  ./backend/tests/test_m1_rework.py
f3cfd7010a4ff66e2c0bb8d92d466c25f330cc386f9278ec78fa67c71e1a4374  ./backend/tests/test_m2.py
7de16727651fc15c1ad828f76f8175fb1a973ba4caba8865a500533be960f375  ./backend/tests/test_m2r.py
390f4f7ab263f6e28b45a17a7dd14d32802922d343fc7fc0d034ead1f31daaba  ./backend/tests/test_m3_m4_m9.py
46baaaf74f9032837367b253916d58b3c1d7679902e88ff66281f9f99e0b1e9e  ./backend/tests/test_m5.py
78d4f0d7576f7da49a9057a89ede129b48ad6a35d0bf187c371a5cf56cd0bc67  ./backend/tests/test_m6.py
7c4358aec29c793e71eddbaf66d5ded9b5c156aab482f1ea7e84c385e24a5a98  ./backend/tests/test_m7.py
de769af1bd12fd1f6de4eb21449ded2debe8dc2e1507c37e7f5ac628f566c5aa  ./backend/tests/test_market_board_api.py
a3d575e76f85fa663ef883319562483f5fd80fcf7da46014bddd26051db7d474  ./backend/tests/test_orderbook_rules.py
80cca4349aac816a2171a71626501e2a7b00d382a4fe58596554da53235b01ac  ./backend/tests/test_orderbook_tape.py
d0c438b848fb53a51398bee2b9dc84c89c64434bd0dc6e4e6d8848f932cb9d1c  ./backend/tests/test_persistence_pg.py
216f6a13ac7abc56968e3a98c56ba7ebc3154db6458d5ec6e735ba7b5cd9275a  ./backend/tests/test_pool_selector_target.py
9c6daa393eb7258a29509ceaa6538d3adfc4bd29f7ffa5c30ecb732815c43549  ./backend/tests/test_rule11_pool_select.py
eb5911e5f87f757681195320d83c6aac32d3c907f051836d9d104fb09c688627  ./backend/tests/test_rule_dsl.py
4fe3e3b76f39fa776e8f072c0082e1ca71d7cb77f38e840bb717ad8eca05ff4a  ./backend/tests/test_rule_registry.py
c365cb6ddce867c1c486448a0827e4746a5d74b0b2041c0909a3c3c8b3a72241  ./backend/tests/test_runtime_params.py
4cbd39276e772a7fe7f2a71c32f4d3d69d66a622bf210b43fa123873cf0c94e7  ./backend/tests/test_sprint4.py
3b6375d570e5093953f484850d14b62612178f63617a7cbfb207cb5ec4d8de83  ./backend/tests/test_strategy_parity.py
ea2a372d6f2ca3ec372ceb3eec6aab725ac0445f450002c311bc2e2a63af355a  ./backend/tests/test_strategy_rules_api.py
2ca5d89c19fcd6fb41a6f6b862311019335fad74f021a02473802b7893024307  ./backend/tests/test_user_manual_kb.py
5d6d383f3bfd28b8500b82377a0b42a62d6b33b8a90bc0485965a7ccb1ade1d5  ./backend/tests/test_verdict_audit.py
bb067ff21c78b779d5689da9834593a45d9cbefb28586ba07321dfbd028d069a  ./backend/tests/test_weight_enrichers.py
c02d70484fe696958cc74a5a702dda845cb638717e4437b6f3ed17cf7df2b420  ./backend/wsgi.py
f6c687b222acd8f70c7a5eb28f759c703193bc4c0994ee8dd96e71c7c3d545b3  ./data_store/1m/000001.csv
76b169bb775b0fb217273b9d072212474d32cf390287f0f6ed14d6f6d03c892b  ./data_store/1m/300750.csv
5cad46bcef920692e6805434acc5f710c5b7fd6ee4893dd3de6774934bebc4e9  ./data_store/1m/600519.csv
9b1316001a769270ff2917175dec9285243e7d3975484a474a39f2c8ae2d95b4  ./docker-compose.prod.yml
7f6f18bc1f89dd12e853437236f0b73406a218c01f1ef2ee9338368e7e20018f  ./docker-compose.yml
5b08a4e58f9a42597eea7dcb71f941825083e04ab78041a574e7a44fbf0a6523  ./docker/env.docker.js
a2ac9b5a2acffe5b831ade7d96392c69105c4ffbd63e93706e994c71412ac43d  ./docker/nginx.conf
51ac9abfec2b5dc2737c6a1930b7c209f8301faec8bd2d0e420b457b706a0639  ./docker/nginx.prod.conf
23421aa43a4d677832e5cc06eb67cf719abda10001087f9327d00f2b7d518d41  ./docs/DEPLOY_CN.md
fd0dd2c5deb0e69ae8cb7c37fcbad07207adbe6e2b388a579ee51112e2339094  ./docs/OPS_RUNBOOK.md
f6b4a6bef8dc62512d80c54c9a556fdd4bced0845fabf46a44adda2713736ad9  ./docs/README.md
62edcb0368bece47c8e1b6e0728c7718c4ec34ef154d348fff7a11235da80629  ./docs/RETENTION.md
f74dc661eb5a928e2246817158b662c80bfa126f71b54aaa1b1bf878b68b313e  ./docs/UX全局走查与优化建议.md
8f26985ec133ac3a6bec2c780adaa993c7cca56de3a36576576b7e40beb5b947  ./docs/返工/README.md
b784356e70dd6929c0e81f3f5eac9dbda23b74336d25fa5ad906e1434888bbe3  ./frontend/app.js
aba30c685ce789b2064d668eb1f829a10e55f16fac0ee7ff343ee59e4f529082  ./frontend/index.html
4ed9e7dafa46625d30eb4e17d18f610b51e5f3f330e9544dc066868b45839f7c  ./frontend/js/advisor.js
f65b4e79c5b4df948c8c646998ce2be95e296f7782e86545156f5b4fecf9cc92  ./frontend/js/api.js
42cb5d845ea53468e5a12848806b69a901e7d9b0ae437471b87e4c10123c0679  ./frontend/js/command.js
752c5354e4c2e513564d185106cd7bed1daa7316a8923bec656c898b2706272b  ./frontend/js/common.js
745d64bf0f77fd9296197e82855d07a496ef17ea101d6bab1100f59ed18f5c3b  ./frontend/js/config.js
4968e5cb0b0804df4340be6b425c8db6955bd50dd40a1e4ec13af2f794148ba9  ./frontend/js/dashboard-terminal.js
2b06b547410c2834864ee600e3e66da43e2e83318b28a9d42ef2055afba9945b  ./frontend/js/dashboard.js
5698135dc28488790ed749ba8781c9ef6db582b31fba34f6ff8ca68603b2a86d  ./frontend/js/env.js
9d2f294979c3a87eb9543c5c131148b97aeb88ee8637d9ac0047db0553899886  ./frontend/js/manual.js
77396e6b071ef4b75756cec4696d8c07c66bb7cd435fb82c7934451a26372bf8  ./frontend/js/performance.js
d78e677e848ac5fceb62696690bcf1268caf0690b69a7164fc29db8102b36d04  ./frontend/js/positions.js
979668353f7a6861075404c9dc7c29a93bccafbec18582f1384dcec96242a8c1  ./frontend/js/signals.js
f7e357a40800eacbd896d2f0c3271b4cec9c12f5fa48bb3efbbd74e730800120  ./frontend/js/simrun.js
a6b448e94e7bfe1ddea8ce2dac175dfee1662c4e28cff3ea6c2bf6f27feff8ab  ./frontend/js/trace.js
d2678eea73c20d464e659199e4f51807b21914e5fbbf1feec8d9f375ce15b856  ./frontend/styles.css
46fc69534ec098f095bbcd1d9a26d693d39a8b9eeff7343536765b3dd28c2bdf  ./frontend/vendor/lightweight-charts.standalone.production.js
934e3e36e9e2da0afb1a6e75075bb0f09af05293a844e84a7477ef40911c349a  ./frontend/vendor/marked.min.js
48298679f9e308f05fdcd5b7421c15fcfb545845a3a99bbaf31033890610eb0b  ./frontend/vendor/purify.min.js
b7206068adc04a7fb52c6d0e61fc5f8018241d4b6e29bfaec87041d11225cc2e  ./migrations/init.sql
fa3ea1bec941edefc45e574eb26f5f2eddf7ef29635ad17fac62a4633b933248  ./reports/M-bt_summary.json
ec5bd9ac23ee333de7f628930e993948f3d273e132aee64813c046b19be76d59  ./reports/M-bt_薄回测报告.md
e6dda7970c9fe9b0e62ca5627e66f385c7407c66407ef64bd0e9913b27667a87  ./scripts/audit_ui_routes.js
eb6b4740e7ac93bae96f9318e7d2574df235472078afb904fe62ebe4ddf708fa  ./scripts/build_astock_sdk.py
4b7dccf00900054f2a163fc8ed6cd869b3e9f512912b6aa51209a65f96837516  ./scripts/deploy-prod.ps1
6652a9737aeabe6da1fa55dd5e8e717ba55937d5982af01da60575bf7ad319f1  ./scripts/deploy-prod.sh
0a892d0fb9b87494b68b82ac835c9949a3635168e5636539cefe85f060ef8949  ./scripts/diag_net.py
765fd6f43331c1b7a59a99898f4ccb6a93857d0f089e6e497f313827de84ca4f  ./scripts/probe_1m_coverage.py
d017277dfa82b6a01e930d779492f11b904a89d64d0c9b16eafb5fc1c1952a33  ./scripts/push-gitee.ps1
6458406059d69c301a9bc169867ee1ea7eb311cac4ce16965153ad96f05f22da  ./scripts/push-gitee.sh
fd40f4b8ff94c73a23d945589fd9aa89375b519dfb8d4c69e671f3d94706599f  ./scripts/record_1m_daily.py
7bcf8c4ed3cd994b4adfe7908d2360060ec55726409e87469cb33d39fda7d88d  ./scripts/retention-purge.ps1
a50d04798cc6bfc0311904232d13a5acfaa67aa9670e7a78a62779059ef501a2  ./scripts/retention-purge.sh
5eb2d2a0d01a303a5a9234c7a6293168911ecf0cae4f0c333bed17afad6534b4  ./scripts/run_thin_backtest.py
24a22d04a86a60da85e6b29102ea0ead91c620f73aa2335dcf357040492fdcd8  ./scripts/server-bootstrap.sh
ebad155071b151d85903498142597c3e170c9287059fcee0d9a25e499b0c398a  ./scripts/server-update.sh
8b43789750ab4d71e25286245bd968e50fef0a7d2e442fee5fefb6289ecca1ec  ./scripts/test_runner.py
81b35b0f4fc47f665472cc364bef2e055f49fdb923f24e7ffdcb1196fdae6311  ./start-dev.py
90563350fe3e3df9907d618ad10aaa5617dc2dc43a01dc83702e025903e54f71  ./start.bat
72f138952743fb3b9463dadd311b633a95e5fd422e421985c489b3f71dee8e17  ./start.ps1
199bab40163ad21135c2c4d5db43bffdadb14ed80762b048f04931cc48700bbf  ./vendor/a-stock-data/LICENSE
c4e2779c44d1255b00382b52ac4ab6456a8e8ce2af8b3aa083b875a421394bfd  ./vendor/a-stock-data/README.md
84fd993471345ff53872bfd2ec86cea915e4fe04637cc65c62580907071de175  ./vendor/a-stock-data/SKILL.md
da37b62b234fc08c3abe13174a58e80da0d1c4cfc5dcf4378e9317e81d4f5c3d  ./vendor/a-stock-data/VERSION
1161ba2336ff91cb2f5cab9a1f4b91c3bd7fd93e075f34875b4574473abee6b3  ./vendor/a-stock-data/a_stock_data_sdk.py
```

## 2. kalshi-paper-trader (Kalshi v1 baseline)

- Local path: `/Users/huhongjie/Documents/Kalshi`
- repo URL: https://github.com/fyjk999-cyber/kalshi-paper-trader.git
- branch: codex/v3-f1-weather-trace
- HEAD commit SHA: fadb6dd2ab7767829948d2ce7a9c5f49bf392c85

### git status --porcelain (BEFORE)

```
?? KALSHI_3_FILL_FORENSIC_REPORT.md
?? KALSHI_CHI_DECISION_METRICS_RCA.md
```

### Key tracked file git object SHAs (blob IDs)
- `lib/v2/decimal.mjs` (git blob): `ec2f24513dc353e1c67a2f3a8d262d7d45a0aca2`
- `lib/v2/ledger.mjs` (git blob): `08f6159960ef148441a5a69e8b508a1ef995bb19`
- `lib/v2/execution-authority.ts` (git blob): `a10feee3cf7a31d45bb4c5e0edd4737cdb221e77`
- `lib/v2/run-lease.ts` (git blob): `d73f9c88c377a83a544093363b6cac99fe363e52`
- `lib/v2/orderbook.mjs` (git blob): `753bd79300b08abe380d8f376ccddbd688d88b4c`
- `lib/v2/replay.mjs` (git blob): `fe21a333d0ac32c1875cfe66caa90cdc19ea49f1`
- `lib/v2/resting-order-ledger.ts` (git blob): `b65078f03dfcae92935241e0f39067376e5f6900`
- `lib/v2/risk.mjs` (git blob): `68698bb0074414b2bfd046020afe59e0de3aca72`
- `lib/v2/engine.ts` (git blob): `6fecc21453fda28ad5113ef3894fb5eb386576c5`
- `lib/v2/run-observability.ts` (git blob): `3d612e17543e162147e52f95ff03122e56d42fea`
- `tests/v2-domain.test.mjs` (git blob): `369c0e75e14a303912a0b0033d1f48560edbab7e`
- `tests/v2-chaos.test.mjs` (git blob): `1a5c8be13a7dbf5fe8c343c7d41f961f507c4fca`
- `tests/v2-sqlite-integration.test.mjs` (git blob): `48f8ec05f4ca1a875c434323d16c3628adb78bc9`
- `tests/v3-runtime-safety.test.mjs` (git blob): `d3eb14c5011ffe79b0449af119a91a989c91adf9`
- `package.json` (git blob): `1d72b69bc021e643635d388fd9c34ffb9a1c70f4`
- `README.md` (git blob): `cdfa5e1e34b9da8ba6a6746fbb7e4185de94245f`

### File tree (tracked)

```
.env.example
.github/workflows/fastf1-sync.yml
.gitignore
.openai/hosting.json
CURRENT_DECISION_ENGINE_REPORT.md
KALSHI_CANDIDATE_FUNNEL_RECOVERY_REPORT.md
KALSHI_FULL_MARKET_OBSERVATION_REPORT.md
KALSHI_KXRAIN_MONTHLY_PRECIP_MODEL_REPORT.md
KALSHI_KXRAIN_OBSERVED_CUTOFF_DEPLOY_REPORT.md
KALSHI_KXRAIN_TIME_WINDOW_CORRECTNESS_REPORT.md
KALSHI_LEVEL3_CONDITION_WATCH_REPORT.md
KALSHI_LIVE_PAPER_VALIDATION_REPORT.md
KALSHI_MAINLINE_CORRECTNESS_GATE_REPORT.md
KALSHI_PROBABILITY_ENGINE_UPGRADE_REPORT.md
KALSHI_PROBABILITY_INTEGRATION_FIX_REPORT.md
KALSHI_PRODUCTION_DIAGNOSTIC_REPORT.md
KALSHI_REAL_PAPER_LIFECYCLE_REPORT.md
PROBABILITY_INTEGRATION_BASELINE.md
README.md
app/api/audit/route.ts
app/api/bot/config/route.ts
app/api/bot/halt/route.ts
app/api/bot/start/route.ts
app/api/credentials/route.ts
app/api/dashboard/route.ts
app/api/f1/route.ts
app/api/internal/daily-review/route.ts
app/api/internal/f1/route.ts
app/api/internal/fia-news/route.ts
app/api/internal/learning/route.ts
app/api/internal/tick/route.ts
app/api/kalshi/route.ts
app/api/learning/report/route.ts
app/api/learning/route.ts
app/api/model-credentials/route.ts
app/api/orders/approve/route.ts
app/api/sports-credentials/route.ts
app/api/sports/route.ts
app/api/strategy-chat/route.ts
app/api/strategy-harness/route.ts
app/api/weather/route.ts
app/chatgpt-auth.ts
app/console-format.ts
app/console-panels.tsx
app/console-types.ts
app/globals.css
app/layout.tsx
app/learning/page.tsx
app/markets/official-feeds-panel.tsx
app/markets/page.tsx
app/page.tsx
app/positions/page.tsx
app/workspace-nav.tsx
artifacts/learning-demo-daily-review.md
artifacts/learning-demo-report.json
build/sites-vite-plugin.ts
config/event-spec.example.json
config/risk.example.json
config/strategy.example.json
db/schema.ts
docs/automation-spec.md
docs/deployment-runbook.md
docs/official-feeds-runbook.md
docs/v2-acceptance.md
docs/v2-api.md
docs/v2-architecture.md
docs/v2-known-limitations.md
docs/v2-phase0-audit.md
docs/v2-runbook.md
docs/v2-security-audit.md
docs/v3-acceptance.md
docs/v3-learning-architecture.md
docs/v3-learning-runbook.md
drizzle/0001_automated_paper_trading.sql
drizzle/0002_owner_scope_and_settlement.sql
drizzle/0003_reviewed_execution.sql
drizzle/0004_strategy_chat.sql
drizzle/0005_sports_data.sql
drizzle/0006_deterministic_v2.sql
drizzle/0007_external_secret_metadata.sql
drizzle/0008_learning_system.sql
drizzle/0009_official_feeds.sql
drizzle/0010_autonomous_learning_hardening.sql
drizzle/0011_fia_news.sql
drizzle/0012_encrypted_secret_vault.sql
drizzle/0013_paper_runs.sql
drizzle/0014_paper_run_idempotency.sql
drizzle/0015_incremental_market_scan.sql
drizzle/0016_f1_replayable_snapshots.sql
drizzle/0017_deepseek_harness_permission.sql
drizzle/0018_probability_decision_engine.sql
drizzle/0019_probability_integration_fix.sql
drizzle/0020_precipitation_calibration.sql
eslint.config.mjs
lib/ai-probability.ts
lib/client-polling.ts
lib/credential-vault.ts
lib/decision-engine.ts
lib/encrypted-secret-vault.mjs
lib/expected-value-engine.ts
lib/f1-feed.ts
lib/f1-model.ts
lib/fair-value-engine.ts
lib/kalshi-readonly.ts
lib/learning/daily-review.ts
lib/learning/episode-builder.ts
lib/learning/evaluation.d.mts
lib/learning/evaluation.mjs
lib/learning/job-lock.ts
lib/learning/learning-policy.ts
lib/learning/profile-registry.ts
lib/learning/proposal.d.mts
lib/learning/proposal.mjs
lib/learning/scheduler.ts
lib/learning/self-reinforcement-guard.d.mts
lib/learning/self-reinforcement-guard.mjs
lib/learning/time-window.d.mts
lib/learning/time-window.mjs
lib/market-book.ts
lib/market-scan.mjs
lib/memory/consolidation.ts
lib/memory/decay.ts
lib/memory/market-regime.d.mts
lib/memory/market-regime.mjs
lib/memory/repository.ts
lib/model-credential-validation.ts
lib/model-review.ts
lib/nws-client.ts
lib/official-models.ts
lib/optimization/engine.ts
lib/optimization/forward-shadow.ts
lib/optimization/parameter-search.d.mts
lib/optimization/parameter-search.mjs
lib/optimization/promotion.d.mts
lib/optimization/promotion.mjs
lib/optimization/replay-engine.d.mts
lib/optimization/replay-engine.mjs
lib/optimization/rollback.ts
lib/optimization/shadow-engine.ts
lib/optimization/walk-forward.d.mts
lib/optimization/walk-forward.mjs
lib/owner-auth.d.mts
lib/owner-auth.mjs
lib/paper-core.d.mts
lib/paper-core.mjs
lib/paper-engine.ts
lib/player-rating.ts
lib/probability-engine.ts
lib/risk-adjusted-position-sizing.ts
lib/server.ts
lib/soft-risk.ts
lib/sports-data.ts
lib/strategy-profile.ts
lib/v2/approved-strategies.ts
lib/v2/audit.ts
lib/v2/bot-control.ts
lib/v2/calibration.d.mts
lib/v2/calibration.mjs
lib/v2/clock.d.mts
lib/v2/clock.mjs
lib/v2/decimal.d.mts
lib/v2/decimal.mjs
lib/v2/engine-support.ts
lib/v2/engine.ts
lib/v2/event-spec.d.mts
lib/v2/event-spec.mjs
lib/v2/evidence.d.mts
lib/v2/evidence.mjs
lib/v2/execution-authority.ts
lib/v2/fees.d.mts
lib/v2/fees.mjs
lib/v2/independent-reviewer.ts
lib/v2/kalshi-websocket.d.mts
lib/v2/kalshi-websocket.mjs
lib/v2/ledger.d.mts
lib/v2/ledger.mjs
lib/v2/llm-safety.d.mts
lib/v2/llm-safety.mjs
lib/v2/maintenance.ts
lib/v2/mutual-exclusion-executor.ts
lib/v2/mutual-exclusion-runtime.ts
lib/v2/official-candidate.ts
lib/v2/orderbook.d.mts
lib/v2/orderbook.mjs
lib/v2/paper-ledger.ts
lib/v2/paper-run.ts
lib/v2/rate-limit.d.mts
lib/v2/rate-limit.mjs
lib/v2/relationship-graph.d.mts
lib/v2/relationship-graph.mjs
lib/v2/replay.d.mts
lib/v2/replay.mjs
lib/v2/resting-order-ledger.ts
lib/v2/resting-orders.d.mts
lib/v2/resting-orders.mjs
lib/v2/risk.d.mts
lib/v2/risk.mjs
lib/v2/run-lease.ts
lib/v2/run-observability.ts
lib/v2/service-budgets.d.mts
lib/v2/service-budgets.mjs
lib/v2/settlement.d.mts
lib/v2/settlement.mjs
lib/v2/signal.d.mts
lib/v2/signal.mjs
lib/v2/start-trigger.ts
lib/v2/strategies.d.mts
lib/v2/strategies.mjs
lib/v2/strategy-registry.d.mts
lib/v2/strategy-registry.mjs
lib/v3/candidate-ranking.mjs
lib/v3/decision-trace.ts
lib/v3/recorded-verdict.ts
lib/weather-feed.ts
lib/weather-stations.ts
next.config.ts
package.json
pnpm-lock.yaml
pnpm-workspace.yaml
postcss.config.mjs
public/favicon.svg
public/og-kalshi-paper.png
requirements-fastf1.txt
scheduler/worker.ts
scheduler/wrangler.jsonc
scripts/demo-learning-v3.mjs
scripts/fastf1_ingest.py
scripts/fia_news.py
scripts/fia_news_ingest.py
scripts/manual-tick-test.mjs
scripts/replay-v2.mjs
tests/account-initialization.test.mjs
tests/autonomous-learning-hardening.test.mjs
tests/diagnostic-pipeline.test.mjs
tests/encrypted-secret-vault.test.mjs
tests/fixtures/kxrain-denver-aug-2026.json
tests/official-feeds.test.mjs
tests/paper-control-routes.test.mjs
tests/paper-engine.test.mjs
tests/paper-simulation-qa.test.mjs
tests/probability-engine.test.mjs
tests/probability-integration-fix.test.mjs
tests/rendered-html.test.mjs
tests/server-safety.test.mjs
tests/sports-data-atomic.test.mjs
tests/sports-trading.test.mjs
tests/test_fia_news.py
tests/v2-chaos.test.mjs
tests/v2-domain.test.mjs
tests/v2-security.test.mjs
tests/v2-sqlite-integration.test.mjs
tests/v3-daily-review-integration.test.mjs
tests/v3-f1-pipeline.test.mjs
tests/v3-learning-domain.test.mjs
tests/v3-learning-scheduler.test.mjs
tests/v3-memory-integration.test.mjs
tests/v3-optimization-integration.test.mjs
tests/v3-rollback-integration.test.mjs
tests/v3-runtime-safety.test.mjs
tests/v3-schema-parity.test.mjs
tests/v3-weekly-consolidation.test.mjs
tsconfig.json
vite.config.ts
worker/index.ts
```

### Worktree aggregate manifest (tracked + untracked, read-only sha256)

```
b201c57bd9f3506ad9fb909070746d0a0e105f157bf34dedc4c7c1bb939cbd37  .env.example
43ab7aec4b1f6bb581fca73dfc95bac1067ec91c723fa19e99650df952f2e71b  .github/workflows/fastf1-sync.yml
b36242913962cd58e93bc243e4bd8e098fcffb173266098ef6f69d0915601654  .gitignore
f5161929ba7cde67dbbdbeac6a0e249e70e017e48c8d556d7c9008d52a146d35  .openai/hosting.json
8d6f74625a4d460a90a58001a79ddac9a6f5dc0c91e555e54ec509047f40a307  CURRENT_DECISION_ENGINE_REPORT.md
a0fbdcd79cbc51252ecb2b814f9662d0e971bb5bc5875ef711759a892ccb1f77  KALSHI_CANDIDATE_FUNNEL_RECOVERY_REPORT.md
d353be5447c467f443f5bd78361af708b43c047b2174cfcfe30ed1f94b64e13b  KALSHI_FULL_MARKET_OBSERVATION_REPORT.md
617eb397caa9080aafb3468e4e130bb91fb44863349a80ed5229b1c75b41ad59  KALSHI_KXRAIN_MONTHLY_PRECIP_MODEL_REPORT.md
081d7d36babcce5f8a4333334d3a943bd7b7b4535b0dc4f1197079cc3e9f6c38  KALSHI_KXRAIN_OBSERVED_CUTOFF_DEPLOY_REPORT.md
db3319304bc89b544c368d2f94863512455a32d45cf8f7f502b68cd552bd13ad  KALSHI_KXRAIN_TIME_WINDOW_CORRECTNESS_REPORT.md
2e7bdbf776336a1dca035459ea40eb229ae8368acce079287567fa0d261c5d40  KALSHI_LEVEL3_CONDITION_WATCH_REPORT.md
f12993fe90575b21e09c1dda01b5ec01ba67a4105612d4f4b16ff487004a4c3d  KALSHI_LIVE_PAPER_VALIDATION_REPORT.md
d02e50bc654cf3566f859870807909fe11e57e1716652fb91506e75da1b36dea  KALSHI_MAINLINE_CORRECTNESS_GATE_REPORT.md
b99c6f08fee7fefdeea5c2825c3447e8dcb8b7ad8e16e7b604d84a7d530d59b3  KALSHI_PROBABILITY_ENGINE_UPGRADE_REPORT.md
df2227fb0ccad6858e817de68dac99868f46115e71752b26ff08e3bdd18f9d2d  KALSHI_PROBABILITY_INTEGRATION_FIX_REPORT.md
c9dcf95b2cb048125d32d4e58f9e3bcbaf774918d11b9b155c766e71af55bb61  KALSHI_PRODUCTION_DIAGNOSTIC_REPORT.md
b5ec7b00398c9d8af8137f2bb541c0a0a540a578851810df49b82a0a58de43f4  KALSHI_REAL_PAPER_LIFECYCLE_REPORT.md
275ae4aad2a1900aba35c0a6185210259ca116ed9cfcdd4026a61412359d201c  PROBABILITY_INTEGRATION_BASELINE.md
23129ded383bf2c89f32f1d188e3f83aacd6f168f3bb3c4a556af99a49d43b40  README.md
795a459f9047a42e7e1ad82f8093600629441b5627a5995837fce041ef953630  app/api/audit/route.ts
faea1b6099088f4cb792aa232a83b4cfcb4481b3a11d795c6684fecd31effe46  app/api/bot/config/route.ts
534e19f3b7d6ab26152aeb8d94abd2912a96f48444e6feb032769aa011640a76  app/api/bot/halt/route.ts
ab15ae541dfe73308a111b82fdfcb86caa7c8f022e04bf0ff05a07218d5fda44  app/api/bot/start/route.ts
41640cb5af33ea5a4bb2bb06f6f8271b88475acacfc2674eb87d915683069267  app/api/credentials/route.ts
6f1bfe81afae8b347cd0edc5c4389a7df309456ebe45d075dc6ca3ed9f33e88e  app/api/dashboard/route.ts
c65b0702e8509ed427b12c9ddcdca6d24e8f7492958dcc3dbabd2a9f2ada99dc  app/api/f1/route.ts
b8774c70e8a382411e5aabf20542685595db6f401d7a884013f88dd8b534c5ec  app/api/internal/daily-review/route.ts
5baa83caa2ea3bd4ea3e7cc71e4be3144a5be7e0e16a620102ca31f898cf22bf  app/api/internal/f1/route.ts
acd32bc9ef000e471ca467046e59c91ea4496306e0a07d5dc89573af57ea8901  app/api/internal/fia-news/route.ts
1ae5658fb5b0dcffedf5dc835d40dd0d876d926a86bb17772e505c7997b09089  app/api/internal/learning/route.ts
17d37f23c0c66853cbabef6c50d73a813dd5954fdb0db66d5fb89fc04c2a3e26  app/api/internal/tick/route.ts
0c71481c38825f0310a0719ec4e93aaf4e073d0809001a589d9d6ecdc5eedcfa  app/api/kalshi/route.ts
d3773973b6bd95be37e28f50cf90909e68f1d7a279a34595c406641df9150478  app/api/learning/report/route.ts
9599df49afbc84e6a89b006d4aa0319e961d2fde0338cb26d958ae3fa698553d  app/api/learning/route.ts
50c68e4e44d29c5257fd144991599f60bc5dc66f38ec8144b46b903f873b3265  app/api/model-credentials/route.ts
e655d61e91378d72c1b6471214c75a0d9f4396dbc07c07fe996fb4d243e36ffc  app/api/orders/approve/route.ts
e91e0edd64e176f17074854495421825e8b064cc75302d89ec363b61ec1ac2b3  app/api/sports-credentials/route.ts
2f83eaf4d135a9c5b0c4cb26d9ca5ea27163618e970ba86835468b5cbb217a89  app/api/sports/route.ts
e232296e7c90c54113557043cf8cd9f9f18167619b2ef5419363a3a2ec0aaad9  app/api/strategy-chat/route.ts
53d9ec82bc6357b3f6a0a2190b190fcbd0aff655032b1e61ab18c217aa3b7665  app/api/strategy-harness/route.ts
85b8a27113d5ee14e99ef92b1d9a6f4c23d35e40507f24ac01245f47df2e2dd6  app/api/weather/route.ts
17a965f8948b21510cdf8ecbd70c5fdf58100e10970463f6a8fd2cc4795f8044  app/chatgpt-auth.ts
2dbd92c212df8abe1c5097b7dfe27223cd6da19e4498364b8ba3a4d91dc0a8fa  app/console-format.ts
e00cb615b63b8eab175531a712f6d67338a6e800f9f8fd21f52b2c472807fb4a  app/console-panels.tsx
ed05b6739c8ffd35d4039b1a43d18e550b0d0c4f1e89bca6db02aa2baf441ddf  app/console-types.ts
c0b39a5a8eb592061a4a88d87176890124787e64aa0e4351a60ab6b9400fde1d  app/globals.css
7ef0e7ffc3e74a532ff59f3ed814181aad5157708c980348e55cfdcd3297b8cc  app/layout.tsx
bc2252469e9fc3e0b4479c1e7dfbeec040677f0dd09fd4958e9bf632998cab59  app/learning/page.tsx
63672d1e0729dc539705a20dee99adca764981924b4202399d6aae35cc313c13  app/markets/official-feeds-panel.tsx
21e3ed6b5dc3166440e17c55d6ef87b82f94ff14a8a1ae7b33794df28a97acd5  app/markets/page.tsx
4e0882979750c647b8dcae86750eb3968ad0eea9e1975c008a159337e8cfadd1  app/page.tsx
bf96b8eb9dcef32000b479c0a47449997e75ade8b8429b595cf4af3ca5a6cdff  app/positions/page.tsx
d6deedc56d713f654d437f0b44c8872bfe6b030c5fdc110650a91b4917b0b8a3  app/workspace-nav.tsx
188f43f5d88b4280ca80e6fd966355ea71c1dc0d056ffd853a893e1087d2c2df  artifacts/learning-demo-daily-review.md
9ecfe74ee931575358c30b7b9271f748665bdedd7c0422d26c526185b09e4721  artifacts/learning-demo-report.json
81b7cbfaeb970611572256aba0e313425beb3809f6426f63750696c15d9c756b  build/sites-vite-plugin.ts
f684e3f5686fe8764e6dbe389b6f66b50929b5648c4136f941df2925eb34082d  config/event-spec.example.json
9a4dd77a85dc30ad8be39ca6c7d9bf21bd6a7322b0b0c6a03477c8e09ae6bd5f  config/risk.example.json
14180795555630f1980c5c9bc06a90163221ac285290b6cc440b0bef5c809358  config/strategy.example.json
a17e6b115b0e3b2efdf3a50b31c310208e42aea9cace2bab8ba749cd6187397a  db/schema.ts
c0071388032b7ff635cd576aacf21d4d8f37c5f8dc3302164c8529b2be7cd00e  docs/automation-spec.md
948aeca40a231551a97f957d177d63dee7cfd919efb5de5675321ee3ed7b4e64  docs/deployment-runbook.md
e04d6ce880a9dbb1d20e9c8980a78216cade83f9553a78d9ac733c78330c1f13  docs/official-feeds-runbook.md
5bba2b6df9958a93161cc8e6132c5b15de2015328459d47714f56001fe2cc35c  docs/v2-acceptance.md
1be95f211e9e0a37d166dcd3f77740ca8863a2de9da08d5d6ced17c230a18232  docs/v2-api.md
30c9066f987df80041b6a20038f95d7e9de16e5ed22aa39b13ddb1433ed025e6  docs/v2-architecture.md
756a2e3c8b089357b649eacb125b30272109a15f86826f61134e939cdaad1cfe  docs/v2-known-limitations.md
c71c5f1975ed412e0c1ebbd09d51ec029aed695f46917d20005a69fe568df763  docs/v2-phase0-audit.md
dcc2635caf14834e3cd072135a30ad1a1639cc2c861955ebfdbbf0aa5b2edc79  docs/v2-runbook.md
9acde49eb0740ab52b12711af657b4a64d5f731a4dc76e26cab9888cf516b723  docs/v2-security-audit.md
251e41481cbff3a26d1fa1510460c8b218e75506c37df12c29289f6e4ec050da  docs/v3-acceptance.md
7def332058ffdcd8c39bbb86f32ee4895d2cdb3a7f833368fabff75df632b5e7  docs/v3-learning-architecture.md
c25343bf165baa690227404ef2c47be6feb5735728379464d70f424a0fafdec9  docs/v3-learning-runbook.md
825807f6eaef119b5f47dc97c33f78215376ba024f424cd6b20f0128673607a3  drizzle/0001_automated_paper_trading.sql
ed43897ff6ed184245db10865a94f65c7e239bb7ee029d49e24a932a49b25b2c  drizzle/0002_owner_scope_and_settlement.sql
0830e0bf7766bbd31c8a7a1c6f4fb9c58116f749f97d2597592b5a3a2ecbfed0  drizzle/0003_reviewed_execution.sql
ca74d973d4fe0ba37da137b7b9496753492ab8abef78f01f218fe65f238ecc59  drizzle/0004_strategy_chat.sql
e32a00433c18f72fe94a28a75bd8c2e129c2fd49b89754d0ac460f587bbd93aa  drizzle/0005_sports_data.sql
d109cf1905b6303ceb526f673f5cf5022e1869876f243eaed36576da146dc973  drizzle/0006_deterministic_v2.sql
d9688177b0697d44ef7b4f3fdaeb7259658a384738f191b1103672ab2de7ab31  drizzle/0007_external_secret_metadata.sql
65fcc6ebcdb109f018484b09b5ba62368b81e4127a14cb7de0488b85dcce9978  drizzle/0008_learning_system.sql
282df5235e3fc6150663072d29960ea7d0faed4314d68cd44cf8465408a7ce6d  drizzle/0009_official_feeds.sql
1c617304570320e80e2a1fce1ca0a533bcd28b8d24431904b39df372f416f0f7  drizzle/0010_autonomous_learning_hardening.sql
95452adefa7bfc38cc2c58f10bc5b9d73453230bc25e56c5d63fd82e03cb2a0f  drizzle/0011_fia_news.sql
260d0f44448c017772f1e5d793a5d2d840a4e60355d81283c714f908d97de799  drizzle/0012_encrypted_secret_vault.sql
3f90c243d8f982a9e6002335fb079bc51c8858bbf8f3a4f9aafcfd159b2efd2f  drizzle/0013_paper_runs.sql
46e0175a8b07abeaac044fc9a9f58dbafb71348eeb629b90989dc4a1e4a2d941  drizzle/0014_paper_run_idempotency.sql
952038b4db3d06edb35cf9c4d3ba8d6b4fa3c8a43c0c2ea1da6c1ddaafa81266  drizzle/0015_incremental_market_scan.sql
4145c5050b1111e04124a8a85bfccee4804c9860ef10e5a92c427a37edcc2f3f  drizzle/0016_f1_replayable_snapshots.sql
c36a25a2636b560511f7eea28d234d3db14f88386f4bc55e37df12a5f084dfe4  drizzle/0017_deepseek_harness_permission.sql
f2ce42ea1d87a576ab846005a50b4a3a7c0033d70ad01869c5d4a8a19242cb2c  drizzle/0018_probability_decision_engine.sql
e9b9c7549ac58e8cd628528ade52896c8fa3d533728227fdca4e29c67e5ea607  drizzle/0019_probability_integration_fix.sql
e1c0265027a01b97ff8d247e0896c28a0d9e2e8045b4283f7aa2f0b038c79c6b  drizzle/0020_precipitation_calibration.sql
870f1adccecf3051cbcd9fd307cef51d7633cf510979c181a81f4b1797273493  eslint.config.mjs
8caa761104fc8ac49256d12f9863db237fa17aa1ba5a59e3813f297d38c67e4d  lib/ai-probability.ts
78c233bdb65ea5ed76e8ece76b92afb2cc236c7de961cf784ffe7e6d5b7a1cd4  lib/client-polling.ts
e845ba171837c233d209ce207eabbc4f678cc882e0e2d60ad135890e127da213  lib/credential-vault.ts
bcf9546712c6a44ad9756ca03c3b7f350952f1993c834549387ff97569e9799e  lib/decision-engine.ts
62e5fc06e8c4ffa2a341953f462676b3d33a88c3cec8835eb29a4a117cd5edfc  lib/encrypted-secret-vault.mjs
b5a1f0ce85ed72f0266e68de5e5e0feac4f84a02c835f28953ecd27f2a946501  lib/expected-value-engine.ts
02f086cc38cde10140a51e836f63d42e6c814337eb04d2ee245df70d57744cd2  lib/f1-feed.ts
4d359b4458cf137c43e6e0351dc13dc1b864000a4ad538f1cac19ccafd227fcd  lib/f1-model.ts
906a368b11ee51e6f55c182e9a71afee92e601b741df9701a6cfdb8ca056416b  lib/fair-value-engine.ts
7b78cc6144fd21564ab50a94528e7e1b930a68d22df6031d03eda134846c291b  lib/kalshi-readonly.ts
7f4eba127cf81de058b7089deb964aeac534ae14b353e2b40ec5c3d03062d17f  lib/learning/daily-review.ts
3c10b2c946c2f2499b987c0be5b413a35f5695738a3c23007356029b6f24ce59  lib/learning/episode-builder.ts
16a093dc7128dde25cf0e1180bd05a387a9ddd19dd998e386fb189889b5c4648  lib/learning/evaluation.d.mts
668f83483f74f397c5b85996259e937bff0514145251af42693e6e9a71b5a47d  lib/learning/evaluation.mjs
017dff545a1648fbb4ff03dd401073651d80ffaa72adf173353a2f83f5ab90b4  lib/learning/job-lock.ts
304a5a6b6688da1ed0aec8287a5bad956d884b04d56fa5922c34c4d9b9186e5a  lib/learning/learning-policy.ts
5911ae295ca9fb2fdc3f3839b1e24dbe3e6b66a3119ff800453a6b4847588b57  lib/learning/profile-registry.ts
818709c589f3523d4f2ebb03c00e5cc5c1f7350f7a5302a2d2f90d61b6676b4a  lib/learning/proposal.d.mts
f2e0ecca22d473e592c1c8ef52c76e5845830610f2e6b0c8e27053d75771d453  lib/learning/proposal.mjs
818f79a786ed93b7053ffd9076729d0b36373081f3bc27dc0a0a2c30c72dac06  lib/learning/scheduler.ts
4ec1159ecfe242f0f10078c02158875ebc57ae08ddc898f602f1aacaf9e54f16  lib/learning/self-reinforcement-guard.d.mts
df81b2ca8ac750ecff6d9fc6d9d3e7aff21cbf865445b37ad5b993b3844e0cef  lib/learning/self-reinforcement-guard.mjs
2ff17018a121639b863e08408be82f803c6504a37ae2394caa2c2e9ef94300c5  lib/learning/time-window.d.mts
133f1e957a6de9b157ca85c5aaa7517ad6e21f456db85b885df82ea4fca05225  lib/learning/time-window.mjs
6a6d299fcbdb0df86b7ce99be7963076db04ae697d1d474cf7c653ed79c91105  lib/market-book.ts
f7683dd23721ba1021ba532451b4eff1fc913b61ab7b9e24a73aad883d2435ea  lib/market-scan.mjs
170712694c7bccfa6dfb7f7d44fa649969ef43a50764c3923babf1f7aeb6d1cc  lib/memory/consolidation.ts
8240b650e0635090dff12a0a78b27123bb1757a43bc6e87996b56c26e4639352  lib/memory/decay.ts
a2664b80d4243102227de3e5ab0309321dc447791ed2545d409d7678e2887112  lib/memory/market-regime.d.mts
404e762a0d89e4da071891e264d2db379bf7dc19cb37f9a7fb67cebe6e99bdac  lib/memory/market-regime.mjs
bab0522c34d0bda5070d8d7fd0613a90dea3fb6b6f574191c69c33ecd3129e38  lib/memory/repository.ts
ae92b716aa20dde29277787abf557cfaadf13b7c9821d70c3ca8453d28b1c6d7  lib/model-credential-validation.ts
970687d300cbeb038d7fddaa5d24cbbd0678dd844b6bcb7ba0de1a5056263dc3  lib/model-review.ts
713f93126b3d1b04d2c799a154c99b5e756aec0cd034a9a2b7dff825acf83332  lib/nws-client.ts
942b6070659e6f76f495956b6e51724656b0cb5928f4308b581917797a934553  lib/official-models.ts
77ddadef865f1c7442e88553b16300824a52d727004e61c38ca72b568a1488ad  lib/optimization/engine.ts
ec5da4a45f1c9c439483482a2e41d65aed03d7be01f64d73d39c9c5a0088d2fc  lib/optimization/forward-shadow.ts
d0fe97c1f83b824a808766fc4132a0caa494161f90ae100a3085ea4a4cfc56ee  lib/optimization/parameter-search.d.mts
cfe7a560c1108a56413faacd5fa3b017a61a5c57bbb7a10f53c311067d716627  lib/optimization/parameter-search.mjs
81f928bda45017a0b43ffc85032e5922ab84178d6f1822bae5c9a17b84b506fa  lib/optimization/promotion.d.mts
f81213dc9aaff06f62d0e5c55ce63e9bdfec454f2e034fdc1875dfa02502eeb3  lib/optimization/promotion.mjs
f5eb0946630e72957810203d47e11779d55900d707803fffc373829bba3514b1  lib/optimization/replay-engine.d.mts
ca8677a84ca0bd2b2981f996c78b3c93df563c8d8704822b0b935918484338aa  lib/optimization/replay-engine.mjs
17706172d5c2e149476da47d2e6e04cf35b5f89ece7ae03ee114dbfa2cf95b92  lib/optimization/rollback.ts
d8fe2f62245b8d5b8c8e8d896e25b5744889338ae7b255a15a95e5a06bcac0d0  lib/optimization/shadow-engine.ts
379b1e0a5369a6ba591157bbc33f9ff60910d29caa69995f92f42ebd7c0d785b  lib/optimization/walk-forward.d.mts
5868cd8f8c2d125319624687e34c553b3e0300711f52325c32259fbc328a4497  lib/optimization/walk-forward.mjs
e595ad8164bd2161cc0ef4c1316732a487166be5aa40c1488c1b0259cb8ca955  lib/owner-auth.d.mts
1a83057e000adc809097675157b826bf4b99e550564701dc417f05912b402e9b  lib/owner-auth.mjs
03114fb73f0ac4fab310a6f3606cf40635e0881e770fb4043bdfe76488b51861  lib/paper-core.d.mts
7f4059f374b23256562e12e031299900514c13d29e2075b4280965beb9bf4cfe  lib/paper-core.mjs
650dacc1f7f36d6cb421047b4dcea5537deca22b2d1731d6344c4adce26c40cc  lib/paper-engine.ts
de081c1735674e39d0d575462757487a230bb740e6c165f95da9ae66730d0639  lib/player-rating.ts
704d509a3d1c2a2cfc946d70e9ddbf62dfcb37c3fadbde4e027d20cb50f0d0d1  lib/probability-engine.ts
a84454bcc71dea2b9a179f77ff2b88307e836eda15a79ae9ac1660f18b2720de  lib/risk-adjusted-position-sizing.ts
39b08aa471883449d6f7b330922f43670463afd644a0d9558b4768a1c1575b65  lib/server.ts
e61a784c1900989410be263830a4bb3e2eb11f624c1134c8f53c060a81651ebe  lib/soft-risk.ts
6e74fbb965e1d5bbe3930be63ddd13a80d3617407854ce5279b15e6f9372546c  lib/sports-data.ts
88e125ff9a9580bfc26fe65e758aa3cbcfd031cac033fee754c565d28b8431be  lib/strategy-profile.ts
1d626b6dffb41d17e17402c70752839bd7e145e5b6c23edaaf3718da0ca6f101  lib/v2/approved-strategies.ts
737d32946f9ddbd6794424289d179b3eb9a010c57faef05fa0a4ea688828d2cf  lib/v2/audit.ts
a8dde77219cc2aff045455298da70a68ee66439594ada05b61c8f4f8b62759f0  lib/v2/bot-control.ts
dac0711ec769fbb904d5590244ac9aef036d975d16a8c2bc044c2523964aa229  lib/v2/calibration.d.mts
644bd75be11b7dbfef8d23d1ac8f19cd4444cebd2d52c041e4ada94019e2739f  lib/v2/calibration.mjs
f8fc7f7509c7bc5ab85c2f830f2e9c2f82b16aabbf30eb839e993090686d664e  lib/v2/clock.d.mts
aae3c494301e741c80ed9b47ceeda9be5fa3b88b8656dd229d3bac8762a26c80  lib/v2/clock.mjs
96f8b4cba9192f1fa9b102c536e11bbd50348b96916551f328f069d78367d284  lib/v2/decimal.d.mts
5ed09ea8814a9adc31a2f5b23310ee4a36d5b17635fb7eb63118e50b007f6228  lib/v2/decimal.mjs
31ce4f0d42fa856f7420238538f6c406d1faa09cfba28e65eca5995cbb37289d  lib/v2/engine-support.ts
128d80af410173f182e40daf51340979176d1a2e1d68428bcea1a996964f1119  lib/v2/engine.ts
ce6ee8e79fca2e95d4416d9b0fd1ff57acc953caa24cc5e47c1f5229da8569b7  lib/v2/event-spec.d.mts
b515bd687f8c22f552d412cb6dc8e5520b308556cd238e6fc3eda3a14cfd4cd5  lib/v2/event-spec.mjs
3ef56b454c5e7aa36ef65934e7eb025c52fac5bcf332563b2a5a5f5c435df954  lib/v2/evidence.d.mts
a67f230b6d46123d67c11529957b1b9f5ade3c2138a2677ad2f5ff0c1c15e2a4  lib/v2/evidence.mjs
994f751d2a2edf8ad5acd39502bf1729d6c41512fa409b23e817fb444dc73b98  lib/v2/execution-authority.ts
1f45ee7cbf9e9f647c9ffa16d1037da8123f3d781ebc225a6da02dac3a27c7d2  lib/v2/fees.d.mts
0dd22a2082f8d397dd15ff55cb510c9355ec060577a24b662f00be692be36100  lib/v2/fees.mjs
16457a0a628640fd03a85ee68f94c8d9eb0a916ac22f59362d646c0f6fcb03b6  lib/v2/independent-reviewer.ts
d6f0dd222f19a02feedc51dde31d2190f1a1683809b1584a05a49344878fb265  lib/v2/kalshi-websocket.d.mts
16d4ad026830769febcc6c52f6fd0850ba552b085b9012666f240a11e8e31130  lib/v2/kalshi-websocket.mjs
04f710fd11b2844a7a7c1309d2ac1ea93d5e38e96d2c4bad5bfca38e98f406e0  lib/v2/ledger.d.mts
ef263efdb63cbaa987b0f95c2b4170959ecc9e2def96696b5baccf09fe584127  lib/v2/ledger.mjs
f076b32138c0f4a9e8b8344e31a2636eb47b98a9c5ea60f4759b8cd3cd4fa40e  lib/v2/llm-safety.d.mts
e734f45d1328eb247aee2015d37f0ec66277a77fc256664aeb21166e83d9b39d  lib/v2/llm-safety.mjs
922d6ec30a1f874afd6e93d6422a251cb77cd6046809116de5dabad0acb92e32  lib/v2/maintenance.ts
f1ee9939f7974f3ff72088dfe5a95fb79c69f5576c1b06f1dbbf0dc5d646c139  lib/v2/mutual-exclusion-executor.ts
40f94590a780acf1ccefcd03458c2f9a180e21a08a9c9f1cd7bd2115e391e256  lib/v2/mutual-exclusion-runtime.ts
89fbf66bef61dafaf1f1df5304dfdd6ca8e05288952e5df2176ae59cef466796  lib/v2/official-candidate.ts
3774cf2f93e26c4e468da01ccd866d226ed50a89ae3853d7419a40b06f679263  lib/v2/orderbook.d.mts
3dfa790f55602e4f7880beb8bae091b463661af5e678ffd63c247c8b97719aab  lib/v2/orderbook.mjs
7fb6992e53e7024c0320b65896d0c8a39cc2e25405b6f28b4447852f64acb0b3  lib/v2/paper-ledger.ts
7c2b0bf866febca6052309aa71f946385ea55dc740e7b918e96334d9596e8719  lib/v2/paper-run.ts
6958648f5eea953da9d3d961aa2b8baf1bb407c8a1bd41c37d92ee2c2e86a896  lib/v2/rate-limit.d.mts
5f40d4e4462dd10eca727b36216e67e8359bc20af7920e8bca06e3e6f832ecf6  lib/v2/rate-limit.mjs
384ec6b0b0e6b92cf975376d897bafe16ee8bcdacad0b168927c7649c2c8ab2e  lib/v2/relationship-graph.d.mts
26f934f6ee487e39e4fb1dfdc82f0f45caab5ccbfa4c0126860891b23ba90e18  lib/v2/relationship-graph.mjs
d54178065d7415793bdb84480ce3405415d01799f96429a00cbf46cb93ca5dc8  lib/v2/replay.d.mts
6eee6ac89a0bd5f4a161b0f2ca65933c12015befcaac4341de880289b9fce191  lib/v2/replay.mjs
793e76b908ac49d6a55907479efce30b0625bb90b58ad4bc8e19f65c2af57f82  lib/v2/resting-order-ledger.ts
c938bb95d359c3ba3c794497bad01c4f40ddbe72f209e7d23dd718c6de44e0bf  lib/v2/resting-orders.d.mts
572c40ec0f7f3cf32d09958296515673932f2b91594f87c622c7d20297236cef  lib/v2/resting-orders.mjs
b0814c11ee183c4ff7f393614fc1f3294d4f260e99086f733a1a9f04998046a5  lib/v2/risk.d.mts
2ad964bf0322f7336030f2e237c7ab04565b45464bd4cb20b07fc6557b92027f  lib/v2/risk.mjs
4214a238010b179b0fd9c332dd0bb8469935ed28e3786d217592810cae847fbb  lib/v2/run-lease.ts
ef8ea1ef2196ae4f51fc7181de7111da43f3c7398e2262397df46152366eb4b0  lib/v2/run-observability.ts
1035e9b3d304e2a7f9ca0c8d94dc85783ff782239c1eca2b1f509b955b92e66a  lib/v2/service-budgets.d.mts
dfc2d9a5da41bf21539793eac7b00a9692d9e805a2a219289dbd8914edc210d6  lib/v2/service-budgets.mjs
43b9b446a8c8a40c64459219acc1c8cd15519086133657bc62af1d3e5a28fd25  lib/v2/settlement.d.mts
454466a5b12227375392c59ac73a30b5e9bd7b4dd1739955fe27d88fe3d47e01  lib/v2/settlement.mjs
72a092fb2142841b813273df2c0ee8b6ec40caf251666a175f0d66ea9d1a55a2  lib/v2/signal.d.mts
62be8758e45ecb7047f895462c75c8ea7dc0aa8d164af456c7be027de5359ab4  lib/v2/signal.mjs
44bb80e6b42cc9394502b7a69c3a9ff2ac64ae8b2d9158e726b1cff42106275d  lib/v2/start-trigger.ts
10796242f34880433abaa0d8de19a3f3413ceab57a96d30703a432f0370878cb  lib/v2/strategies.d.mts
2a490adb998c5910525281e93631d411a13aa2f031cdb3d95f6c94c2ddfe28b5  lib/v2/strategies.mjs
38cb147fffd705869e4d65817f55a420b839339de32343cda26ec3d53790e740  lib/v2/strategy-registry.d.mts
0a25e51d7ce8f10e892edfc40e15c20ed0e2668a9a5e15003ca55d995431de19  lib/v2/strategy-registry.mjs
341f29e015d7524851b4099c12991728809087dc834bc78ce447ed22fbbac415  lib/v3/candidate-ranking.mjs
6ef74dbfcd0959443a0fbacf6ec078aae74cd33fc580ad43d071f136232d9bd9  lib/v3/decision-trace.ts
5d34e9487d3683c60ac46ca60fe957433e13a9791a88eb678da16b4287cdf7bd  lib/v3/recorded-verdict.ts
91c59d4bb23a7e58f7ab929020dc11a6951f70872ebd068e7a6a6691bee213d9  lib/weather-feed.ts
07335d88c4db291151ba5d779153d01ef7c8aee55d94dda76d802b4cabf4c949  lib/weather-stations.ts
614bce25b089c3f19b1e17a6346c74b858034040154c6621e7d35303004767cc  next.config.ts
957912c7888102e14c28eadb40e6aa55d06503bbfc056b865e681bdb497ce601  package.json
89abd8a345887e30d1a5bcc9d4426fb4d7c0a813e26eab5ddc554299b6250f25  pnpm-lock.yaml
fb4cd1144091d2d15ef21d607c27abe15bc40a45e1b7828ae50e232eabde3e78  pnpm-workspace.yaml
dfac7ac2d86d326a0e5adb024e7943c181393ed17a5fcb8f0315b24c7da6ddde  postcss.config.mjs
e6d2e59b7b5bbb0342e0fb496dfc262decbfe4426bbb7b047aec8d467d1dc6f7  public/favicon.svg
a8c98351cf8071e0de850ae825b38e81320a7654ad8cb6c3c0d1dcedea0e9bb5  public/og-kalshi-paper.png
829d0e3c78b12de6ca77eec03c649c4daaf5c40523c0d1ecd5da658df47f36e5  requirements-fastf1.txt
6527e155fd79e19921c2f2314b9b42ac0a03fbdc7665b70151b71cedf3e235e4  scheduler/worker.ts
8abdea7111a5c09c2d37db1d58cfec81fa1fe7aa89f5974788f08171ec210d40  scheduler/wrangler.jsonc
2234ceddc5e70cf4e2b5d9d5370fc46140c28e3937a1df8310eec1e9eb5b219f  scripts/demo-learning-v3.mjs
21ea87aa7fb9798fb87b6b2b0fc63c1f5cf0b58d16f30acf5c5ce10d75a0a118  scripts/fastf1_ingest.py
2cdbb2bb48aca68e5c85a931a87f3753b83e7c7d44c80312ecf5240ec8972c0e  scripts/fia_news.py
3aa711262289d3066852cf26697a241a3faf029b89e7c5563493be0b52bddf5d  scripts/fia_news_ingest.py
00f80b42b4645c1c8181480e85b77571c4fda150d9ad5e61bccdff9e15727db7  scripts/manual-tick-test.mjs
424050ba1ddfd09670bc891fff816dd131f03707a142e36a99eaee05d0d55142  scripts/replay-v2.mjs
655d73998e377e35b4c9e71174eb8eac69c535eecd658b83aaf91e0b2cf45448  tests/account-initialization.test.mjs
1911649e63903368b12b075c11a6460edb844ce8ee908a14d97da53d7895e636  tests/autonomous-learning-hardening.test.mjs
2b838dccb5320598a034b65ec5defa33503c1796b02a69c3b381e8fb7d48845f  tests/diagnostic-pipeline.test.mjs
0a9644976f7dff57faee6c6da47abc8d31c55fcda5b19b665ee50d0ee0bd2f64  tests/encrypted-secret-vault.test.mjs
af75b2c30ee924ef0e9906c14dc853fcb9d33480835fa7a894de4b20ef4ee625  tests/fixtures/kxrain-denver-aug-2026.json
4510ec5313dd47b4e2cf04c0e63c7c5926eac466cf976238ace865bf83710f02  tests/official-feeds.test.mjs
1d25044825955e0a8445918c486faac5da5218b2fc8b3ce05a649a66e34a5576  tests/paper-control-routes.test.mjs
2b049233aaee61d2c649e6927a2100836690c877deb8eb91aec9eb6ef9a0a024  tests/paper-engine.test.mjs
5c31c9c626d04ec3f3b28fb315539d20dfb75bc7da2e2a2c9f8e8e58ab841e2e  tests/paper-simulation-qa.test.mjs
06d9bc841798d9cd8aa894ce2d486b204302305cdf58de7a7ca2e8d87808f3c9  tests/probability-engine.test.mjs
d3501bd969c5bae954b13219be9160ca6144422049bb87afec214830b357e869  tests/probability-integration-fix.test.mjs
4158300355a0636acfc3d619250c6c3a3223e687e60b451b534ce80b53fc39b8  tests/rendered-html.test.mjs
6c5dc0c6312c134c27f8043f90a65c071a8260d8d95f9797116fb951f6dc1384  tests/server-safety.test.mjs
9a172a4d03450c86a0041dc6f517ec3ea18a3b23bf3f84f6dc97b5c2be836168  tests/sports-data-atomic.test.mjs
2513a722dbec2b1c2c1f2ee89c172aefd7fba0a8021a40692f6bc87825ea66a9  tests/sports-trading.test.mjs
3478762d330bde0c9a28712151c88c8a5221ac36f730d0a50c457a48a0a2c352  tests/test_fia_news.py
22f5ad36020e65ff15aa4b5cd04bc72afa2e365c64d9e01b6cb657266021cb65  tests/v2-chaos.test.mjs
77f09cac902b2c5209c3e1f99ee3a72c242c0d337e67382a731b9c8d32eea5e5  tests/v2-domain.test.mjs
4bb96dbb3eac0beb409d9d5a863ea987bddaec6ef8860c3948861e801781ddc3  tests/v2-security.test.mjs
d305987f05cfb806103f0db3da0bf1f17e4b66cec4eb9fa847ee88ad45de114d  tests/v2-sqlite-integration.test.mjs
a9fb4260dccdff0375756decb184a5bd9f496ca279a2bad0d94d26d406ae7bac  tests/v3-daily-review-integration.test.mjs
5fb55415f972f9754e390953d1fbd79a96eef2d01ec278bb726e1e4aa376a65e  tests/v3-f1-pipeline.test.mjs
fc581c83034da1c8262515f6ee926e83454742e13c2cbd16ea242f517da8cb7e  tests/v3-learning-domain.test.mjs
cba89722aa4d2d9385657bb7360e8b37cfe0ebf71302e48d7118c5ac367d4ab5  tests/v3-learning-scheduler.test.mjs
b692210da3230998c31e55e94ef4b5f17b0498d17d97a3d9029b0b2de34927b7  tests/v3-memory-integration.test.mjs
b803543631662817d5e5cf0a3598830a171c0dc1b18732bab532af88eec8f67f  tests/v3-optimization-integration.test.mjs
2fdc19da0aaa07cbada88b8a9623bd50b920cfd7f6f1ee3ac6be398bb53ee8e7  tests/v3-rollback-integration.test.mjs
0433593998fbbd93524aa8ba1ed049708a56ad8d06427fbd31106239ef5ebe5d  tests/v3-runtime-safety.test.mjs
6328fda6d13703e2da5ef49949d3f4e18a91eef9202065c734ef35359699840e  tests/v3-schema-parity.test.mjs
4bf9e8832c184f32089343b604ce636cdf590f49faa7069499954f71326bb24c  tests/v3-weekly-consolidation.test.mjs
9b92cfa2e569828f8b7d14e89beadc88b56085d283976a571ca022aea0c8da23  tsconfig.json
7f2e4956bd5684b32fd0104200f8d4e0b8c12a6b615ebb9f9332031318bfbeaa  vite.config.ts
5785dcc71d48d9a157e5306fe623310d62f4465d0c3a42aaf201856d30ff8208  worker/index.ts
d6165e43a954e65a0e2a3cb1e5c5082746bf224844e5d2e850b91bedc8a79d25  KALSHI_3_FILL_FORENSIC_REPORT.md
58e7d435cb0e1f133eef8ace36008231e3ec9777055a19c73869c4dfb994a986  KALSHI_CHI_DECISION_METRICS_RCA.md
```

## 3. kalshi-paper-trader-v2 (Kalshi v2 baseline)

- Local path: `/Users/huhongjie/Desktop/kalshi`
- repo URL: https://github.com/fyjk999-cyber/kalshi-paper-trader-v2.git
- branch: codex/v3-f1-weather-trace
- HEAD commit SHA: 7cc5d25ca770be03e4098cdcc1b5da38659a398c

### git status --porcelain (BEFORE)

```
```

### Key tracked file git object SHAs (blob IDs)
- `lib/v2/decimal.mjs` (git blob): `ec2f24513dc353e1c67a2f3a8d262d7d45a0aca2`
- `lib/v2/ledger.mjs` (git blob): `08f6159960ef148441a5a69e8b508a1ef995bb19`
- `lib/v2/execution-authority.ts` (git blob): `a10feee3cf7a31d45bb4c5e0edd4737cdb221e77`
- `lib/v2/run-lease.ts` (git blob): `d73f9c88c377a83a544093363b6cac99fe363e52`
- `lib/v2/orderbook.mjs` (git blob): `753bd79300b08abe380d8f376ccddbd688d88b4c`
- `lib/v2/replay.mjs` (git blob): `fe21a333d0ac32c1875cfe66caa90cdc19ea49f1`
- `lib/v2/resting-order-ledger.ts` (git blob): `b65078f03dfcae92935241e0f39067376e5f6900`
- `lib/v2/risk.mjs` (git blob): `68698bb0074414b2bfd046020afe59e0de3aca72`
- `lib/v2/engine.ts` (git blob): `f8fbf5a91d7d8a4893c663c71709fef428d7048c`
- `lib/v2/run-observability.ts` (git blob): `3bed02cb8b5f32ba3ad9a0a90858f294c1b9d218`
- `tests/v2-domain.test.mjs` (git blob): `7c7802e14b909a610ba35d91fdcc70e165e05ff3`
- `tests/v2-chaos.test.mjs` (git blob): `1a5c8be13a7dbf5fe8c343c7d41f961f507c4fca`
- `tests/v2-sqlite-integration.test.mjs` (git blob): `e03fa805ca211a3830084b570c05503dfa8063b4`
- `tests/v3-runtime-safety.test.mjs` (git blob): `d3eb14c5011ffe79b0449af119a91a989c91adf9`
- `package.json` (git blob): `1d72b69bc021e643635d388fd9c34ffb9a1c70f4`
- `README.md` (git blob): `cdfa5e1e34b9da8ba6a6746fbb7e4185de94245f`

### File tree (tracked)

```
.env.example
.github/workflows/fastf1-sync.yml
.gitignore
.openai/hosting.json
CURRENT_DECISION_ENGINE_REPORT.md
KALSHI_LIVE_PAPER_VALIDATION_REPORT.md
KALSHI_PROBABILITY_ENGINE_UPGRADE_REPORT.md
KALSHI_PROBABILITY_INTEGRATION_FIX_REPORT.md
KALSHI_PRODUCTION_DIAGNOSTIC_REPORT.md
PROBABILITY_INTEGRATION_BASELINE.md
README.md
app/api/audit/route.ts
app/api/bot/config/route.ts
app/api/bot/halt/route.ts
app/api/bot/start/route.ts
app/api/credentials/route.ts
app/api/dashboard/route.ts
app/api/f1/route.ts
app/api/internal/daily-review/route.ts
app/api/internal/f1/route.ts
app/api/internal/fia-news/route.ts
app/api/internal/learning/route.ts
app/api/internal/tick/route.ts
app/api/kalshi/route.ts
app/api/learning/report/route.ts
app/api/learning/route.ts
app/api/model-credentials/route.ts
app/api/orders/approve/route.ts
app/api/sports-credentials/route.ts
app/api/sports/route.ts
app/api/strategy-chat/route.ts
app/api/strategy-harness/route.ts
app/api/weather/route.ts
app/chatgpt-auth.ts
app/console-format.ts
app/console-panels.tsx
app/console-types.ts
app/globals.css
app/layout.tsx
app/learning/page.tsx
app/markets/official-feeds-panel.tsx
app/markets/page.tsx
app/page.tsx
app/positions/page.tsx
app/workspace-nav.tsx
artifacts/learning-demo-daily-review.md
artifacts/learning-demo-report.json
build/sites-vite-plugin.ts
config/event-spec.example.json
config/risk.example.json
config/strategy.example.json
db/schema.ts
docs/automation-spec.md
docs/deployment-runbook.md
docs/official-feeds-runbook.md
docs/v2-acceptance.md
docs/v2-api.md
docs/v2-architecture.md
docs/v2-known-limitations.md
docs/v2-phase0-audit.md
docs/v2-runbook.md
docs/v2-security-audit.md
docs/v3-acceptance.md
docs/v3-learning-architecture.md
docs/v3-learning-runbook.md
drizzle/0001_automated_paper_trading.sql
drizzle/0002_owner_scope_and_settlement.sql
drizzle/0003_reviewed_execution.sql
drizzle/0004_strategy_chat.sql
drizzle/0005_sports_data.sql
drizzle/0006_deterministic_v2.sql
drizzle/0007_external_secret_metadata.sql
drizzle/0008_learning_system.sql
drizzle/0009_official_feeds.sql
drizzle/0010_autonomous_learning_hardening.sql
drizzle/0011_fia_news.sql
drizzle/0012_encrypted_secret_vault.sql
drizzle/0013_paper_runs.sql
drizzle/0014_paper_run_idempotency.sql
drizzle/0015_incremental_market_scan.sql
drizzle/0016_f1_replayable_snapshots.sql
drizzle/0017_deepseek_harness_permission.sql
drizzle/0018_probability_decision_engine.sql
drizzle/0019_probability_integration_fix.sql
eslint.config.mjs
lib/ai-probability.ts
lib/client-polling.ts
lib/credential-vault.ts
lib/decision-engine.ts
lib/encrypted-secret-vault.mjs
lib/expected-value-engine.ts
lib/f1-feed.ts
lib/f1-model.ts
lib/fair-value-engine.ts
lib/kalshi-readonly.ts
lib/learning/daily-review.ts
lib/learning/episode-builder.ts
lib/learning/evaluation.d.mts
lib/learning/evaluation.mjs
lib/learning/job-lock.ts
lib/learning/learning-policy.ts
lib/learning/profile-registry.ts
lib/learning/proposal.d.mts
lib/learning/proposal.mjs
lib/learning/scheduler.ts
lib/learning/self-reinforcement-guard.d.mts
lib/learning/self-reinforcement-guard.mjs
lib/learning/time-window.d.mts
lib/learning/time-window.mjs
lib/market-book.ts
lib/market-scan.mjs
lib/memory/consolidation.ts
lib/memory/decay.ts
lib/memory/market-regime.d.mts
lib/memory/market-regime.mjs
lib/memory/repository.ts
lib/model-credential-validation.ts
lib/model-review.ts
lib/nws-client.ts
lib/official-models.ts
lib/optimization/engine.ts
lib/optimization/forward-shadow.ts
lib/optimization/parameter-search.d.mts
lib/optimization/parameter-search.mjs
lib/optimization/promotion.d.mts
lib/optimization/promotion.mjs
lib/optimization/replay-engine.d.mts
lib/optimization/replay-engine.mjs
lib/optimization/rollback.ts
lib/optimization/shadow-engine.ts
lib/optimization/walk-forward.d.mts
lib/optimization/walk-forward.mjs
lib/owner-auth.d.mts
lib/owner-auth.mjs
lib/paper-core.d.mts
lib/paper-core.mjs
lib/paper-engine.ts
lib/player-rating.ts
lib/probability-engine.ts
lib/risk-adjusted-position-sizing.ts
lib/server.ts
lib/soft-risk.ts
lib/sports-data.ts
lib/strategy-profile.ts
lib/v2/approved-strategies.ts
lib/v2/audit.ts
lib/v2/bot-control.ts
lib/v2/calibration.d.mts
lib/v2/calibration.mjs
lib/v2/clock.d.mts
lib/v2/clock.mjs
lib/v2/decimal.d.mts
lib/v2/decimal.mjs
lib/v2/engine-support.ts
lib/v2/engine.ts
lib/v2/event-spec.d.mts
lib/v2/event-spec.mjs
lib/v2/evidence.d.mts
lib/v2/evidence.mjs
lib/v2/execution-authority.ts
lib/v2/fees.d.mts
lib/v2/fees.mjs
lib/v2/independent-reviewer.ts
lib/v2/kalshi-websocket.d.mts
lib/v2/kalshi-websocket.mjs
lib/v2/ledger.d.mts
lib/v2/ledger.mjs
lib/v2/llm-safety.d.mts
lib/v2/llm-safety.mjs
lib/v2/maintenance.ts
lib/v2/mutual-exclusion-executor.ts
lib/v2/mutual-exclusion-runtime.ts
lib/v2/official-candidate.ts
lib/v2/orderbook.d.mts
lib/v2/orderbook.mjs
lib/v2/paper-ledger.ts
lib/v2/paper-run.ts
lib/v2/rate-limit.d.mts
lib/v2/rate-limit.mjs
lib/v2/relationship-graph.d.mts
lib/v2/relationship-graph.mjs
lib/v2/replay.d.mts
lib/v2/replay.mjs
lib/v2/resting-order-ledger.ts
lib/v2/resting-orders.d.mts
lib/v2/resting-orders.mjs
lib/v2/risk.d.mts
lib/v2/risk.mjs
lib/v2/run-lease.ts
lib/v2/run-observability.ts
lib/v2/service-budgets.d.mts
lib/v2/service-budgets.mjs
lib/v2/settlement.d.mts
lib/v2/settlement.mjs
lib/v2/signal.d.mts
lib/v2/signal.mjs
lib/v2/start-trigger.ts
lib/v2/strategies.d.mts
lib/v2/strategies.mjs
lib/v2/strategy-registry.d.mts
lib/v2/strategy-registry.mjs
lib/v3/candidate-ranking.mjs
lib/v3/decision-trace.ts
lib/v3/recorded-verdict.ts
lib/weather-feed.ts
lib/weather-stations.ts
next.config.ts
package.json
pnpm-lock.yaml
pnpm-workspace.yaml
postcss.config.mjs
public/favicon.svg
public/og-kalshi-paper.png
requirements-fastf1.txt
scheduler/worker.ts
scheduler/wrangler.jsonc
scripts/demo-learning-v3.mjs
scripts/fastf1_ingest.py
scripts/fia_news.py
scripts/fia_news_ingest.py
scripts/manual-tick-test.mjs
scripts/replay-v2.mjs
tests/account-initialization.test.mjs
tests/autonomous-learning-hardening.test.mjs
tests/diagnostic-pipeline.test.mjs
tests/encrypted-secret-vault.test.mjs
tests/official-feeds.test.mjs
tests/paper-control-routes.test.mjs
tests/paper-engine.test.mjs
tests/paper-simulation-qa.test.mjs
tests/probability-engine.test.mjs
tests/probability-integration-fix.test.mjs
tests/rendered-html.test.mjs
tests/server-safety.test.mjs
tests/sports-data-atomic.test.mjs
tests/sports-trading.test.mjs
tests/test_fia_news.py
tests/v2-chaos.test.mjs
tests/v2-domain.test.mjs
tests/v2-security.test.mjs
tests/v2-sqlite-integration.test.mjs
tests/v3-daily-review-integration.test.mjs
tests/v3-f1-pipeline.test.mjs
tests/v3-learning-domain.test.mjs
tests/v3-learning-scheduler.test.mjs
tests/v3-memory-integration.test.mjs
tests/v3-optimization-integration.test.mjs
tests/v3-rollback-integration.test.mjs
tests/v3-runtime-safety.test.mjs
tests/v3-schema-parity.test.mjs
tests/v3-weekly-consolidation.test.mjs
tsconfig.json
vite.config.ts
worker/index.ts
```

### Worktree aggregate manifest (tracked + untracked, read-only sha256)

```
b201c57bd9f3506ad9fb909070746d0a0e105f157bf34dedc4c7c1bb939cbd37  .env.example
43ab7aec4b1f6bb581fca73dfc95bac1067ec91c723fa19e99650df952f2e71b  .github/workflows/fastf1-sync.yml
b36242913962cd58e93bc243e4bd8e098fcffb173266098ef6f69d0915601654  .gitignore
f5161929ba7cde67dbbdbeac6a0e249e70e017e48c8d556d7c9008d52a146d35  .openai/hosting.json
8d6f74625a4d460a90a58001a79ddac9a6f5dc0c91e555e54ec509047f40a307  CURRENT_DECISION_ENGINE_REPORT.md
f12993fe90575b21e09c1dda01b5ec01ba67a4105612d4f4b16ff487004a4c3d  KALSHI_LIVE_PAPER_VALIDATION_REPORT.md
b99c6f08fee7fefdeea5c2825c3447e8dcb8b7ad8e16e7b604d84a7d530d59b3  KALSHI_PROBABILITY_ENGINE_UPGRADE_REPORT.md
df2227fb0ccad6858e817de68dac99868f46115e71752b26ff08e3bdd18f9d2d  KALSHI_PROBABILITY_INTEGRATION_FIX_REPORT.md
c9dcf95b2cb048125d32d4e58f9e3bcbaf774918d11b9b155c766e71af55bb61  KALSHI_PRODUCTION_DIAGNOSTIC_REPORT.md
275ae4aad2a1900aba35c0a6185210259ca116ed9cfcdd4026a61412359d201c  PROBABILITY_INTEGRATION_BASELINE.md
23129ded383bf2c89f32f1d188e3f83aacd6f168f3bb3c4a556af99a49d43b40  README.md
795a459f9047a42e7e1ad82f8093600629441b5627a5995837fce041ef953630  app/api/audit/route.ts
faea1b6099088f4cb792aa232a83b4cfcb4481b3a11d795c6684fecd31effe46  app/api/bot/config/route.ts
534e19f3b7d6ab26152aeb8d94abd2912a96f48444e6feb032769aa011640a76  app/api/bot/halt/route.ts
ab15ae541dfe73308a111b82fdfcb86caa7c8f022e04bf0ff05a07218d5fda44  app/api/bot/start/route.ts
41640cb5af33ea5a4bb2bb06f6f8271b88475acacfc2674eb87d915683069267  app/api/credentials/route.ts
6f1bfe81afae8b347cd0edc5c4389a7df309456ebe45d075dc6ca3ed9f33e88e  app/api/dashboard/route.ts
c65b0702e8509ed427b12c9ddcdca6d24e8f7492958dcc3dbabd2a9f2ada99dc  app/api/f1/route.ts
b8774c70e8a382411e5aabf20542685595db6f401d7a884013f88dd8b534c5ec  app/api/internal/daily-review/route.ts
5baa83caa2ea3bd4ea3e7cc71e4be3144a5be7e0e16a620102ca31f898cf22bf  app/api/internal/f1/route.ts
acd32bc9ef000e471ca467046e59c91ea4496306e0a07d5dc89573af57ea8901  app/api/internal/fia-news/route.ts
1ae5658fb5b0dcffedf5dc835d40dd0d876d926a86bb17772e505c7997b09089  app/api/internal/learning/route.ts
17d37f23c0c66853cbabef6c50d73a813dd5954fdb0db66d5fb89fc04c2a3e26  app/api/internal/tick/route.ts
0c71481c38825f0310a0719ec4e93aaf4e073d0809001a589d9d6ecdc5eedcfa  app/api/kalshi/route.ts
d3773973b6bd95be37e28f50cf90909e68f1d7a279a34595c406641df9150478  app/api/learning/report/route.ts
9599df49afbc84e6a89b006d4aa0319e961d2fde0338cb26d958ae3fa698553d  app/api/learning/route.ts
50c68e4e44d29c5257fd144991599f60bc5dc66f38ec8144b46b903f873b3265  app/api/model-credentials/route.ts
e655d61e91378d72c1b6471214c75a0d9f4396dbc07c07fe996fb4d243e36ffc  app/api/orders/approve/route.ts
e91e0edd64e176f17074854495421825e8b064cc75302d89ec363b61ec1ac2b3  app/api/sports-credentials/route.ts
2f83eaf4d135a9c5b0c4cb26d9ca5ea27163618e970ba86835468b5cbb217a89  app/api/sports/route.ts
e232296e7c90c54113557043cf8cd9f9f18167619b2ef5419363a3a2ec0aaad9  app/api/strategy-chat/route.ts
53d9ec82bc6357b3f6a0a2190b190fcbd0aff655032b1e61ab18c217aa3b7665  app/api/strategy-harness/route.ts
85b8a27113d5ee14e99ef92b1d9a6f4c23d35e40507f24ac01245f47df2e2dd6  app/api/weather/route.ts
17a965f8948b21510cdf8ecbd70c5fdf58100e10970463f6a8fd2cc4795f8044  app/chatgpt-auth.ts
2dbd92c212df8abe1c5097b7dfe27223cd6da19e4498364b8ba3a4d91dc0a8fa  app/console-format.ts
a79cde4b12353449d5dedb9ad0191ea11b8376e0dca33a836d3f629fd397f984  app/console-panels.tsx
300e69fde05b48f9f9f15a28858d6339c5374abaeb8d50948e64576bcf07670b  app/console-types.ts
c0b39a5a8eb592061a4a88d87176890124787e64aa0e4351a60ab6b9400fde1d  app/globals.css
7ef0e7ffc3e74a532ff59f3ed814181aad5157708c980348e55cfdcd3297b8cc  app/layout.tsx
bc2252469e9fc3e0b4479c1e7dfbeec040677f0dd09fd4958e9bf632998cab59  app/learning/page.tsx
63672d1e0729dc539705a20dee99adca764981924b4202399d6aae35cc313c13  app/markets/official-feeds-panel.tsx
21e3ed6b5dc3166440e17c55d6ef87b82f94ff14a8a1ae7b33794df28a97acd5  app/markets/page.tsx
4e0882979750c647b8dcae86750eb3968ad0eea9e1975c008a159337e8cfadd1  app/page.tsx
bf96b8eb9dcef32000b479c0a47449997e75ade8b8429b595cf4af3ca5a6cdff  app/positions/page.tsx
d6deedc56d713f654d437f0b44c8872bfe6b030c5fdc110650a91b4917b0b8a3  app/workspace-nav.tsx
188f43f5d88b4280ca80e6fd966355ea71c1dc0d056ffd853a893e1087d2c2df  artifacts/learning-demo-daily-review.md
9ecfe74ee931575358c30b7b9271f748665bdedd7c0422d26c526185b09e4721  artifacts/learning-demo-report.json
81b7cbfaeb970611572256aba0e313425beb3809f6426f63750696c15d9c756b  build/sites-vite-plugin.ts
f684e3f5686fe8764e6dbe389b6f66b50929b5648c4136f941df2925eb34082d  config/event-spec.example.json
9a4dd77a85dc30ad8be39ca6c7d9bf21bd6a7322b0b0c6a03477c8e09ae6bd5f  config/risk.example.json
14180795555630f1980c5c9bc06a90163221ac285290b6cc440b0bef5c809358  config/strategy.example.json
b892ecafce1828c2d7713ca419be2a641439d38f3dd448897fc2a6b8c9bf14bf  db/schema.ts
c0071388032b7ff635cd576aacf21d4d8f37c5f8dc3302164c8529b2be7cd00e  docs/automation-spec.md
948aeca40a231551a97f957d177d63dee7cfd919efb5de5675321ee3ed7b4e64  docs/deployment-runbook.md
e04d6ce880a9dbb1d20e9c8980a78216cade83f9553a78d9ac733c78330c1f13  docs/official-feeds-runbook.md
5bba2b6df9958a93161cc8e6132c5b15de2015328459d47714f56001fe2cc35c  docs/v2-acceptance.md
1be95f211e9e0a37d166dcd3f77740ca8863a2de9da08d5d6ced17c230a18232  docs/v2-api.md
30c9066f987df80041b6a20038f95d7e9de16e5ed22aa39b13ddb1433ed025e6  docs/v2-architecture.md
756a2e3c8b089357b649eacb125b30272109a15f86826f61134e939cdaad1cfe  docs/v2-known-limitations.md
c71c5f1975ed412e0c1ebbd09d51ec029aed695f46917d20005a69fe568df763  docs/v2-phase0-audit.md
dcc2635caf14834e3cd072135a30ad1a1639cc2c861955ebfdbbf0aa5b2edc79  docs/v2-runbook.md
9acde49eb0740ab52b12711af657b4a64d5f731a4dc76e26cab9888cf516b723  docs/v2-security-audit.md
251e41481cbff3a26d1fa1510460c8b218e75506c37df12c29289f6e4ec050da  docs/v3-acceptance.md
7def332058ffdcd8c39bbb86f32ee4895d2cdb3a7f833368fabff75df632b5e7  docs/v3-learning-architecture.md
c25343bf165baa690227404ef2c47be6feb5735728379464d70f424a0fafdec9  docs/v3-learning-runbook.md
825807f6eaef119b5f47dc97c33f78215376ba024f424cd6b20f0128673607a3  drizzle/0001_automated_paper_trading.sql
ed43897ff6ed184245db10865a94f65c7e239bb7ee029d49e24a932a49b25b2c  drizzle/0002_owner_scope_and_settlement.sql
0830e0bf7766bbd31c8a7a1c6f4fb9c58116f749f97d2597592b5a3a2ecbfed0  drizzle/0003_reviewed_execution.sql
ca74d973d4fe0ba37da137b7b9496753492ab8abef78f01f218fe65f238ecc59  drizzle/0004_strategy_chat.sql
e32a00433c18f72fe94a28a75bd8c2e129c2fd49b89754d0ac460f587bbd93aa  drizzle/0005_sports_data.sql
d109cf1905b6303ceb526f673f5cf5022e1869876f243eaed36576da146dc973  drizzle/0006_deterministic_v2.sql
d9688177b0697d44ef7b4f3fdaeb7259658a384738f191b1103672ab2de7ab31  drizzle/0007_external_secret_metadata.sql
65fcc6ebcdb109f018484b09b5ba62368b81e4127a14cb7de0488b85dcce9978  drizzle/0008_learning_system.sql
282df5235e3fc6150663072d29960ea7d0faed4314d68cd44cf8465408a7ce6d  drizzle/0009_official_feeds.sql
1c617304570320e80e2a1fce1ca0a533bcd28b8d24431904b39df372f416f0f7  drizzle/0010_autonomous_learning_hardening.sql
95452adefa7bfc38cc2c58f10bc5b9d73453230bc25e56c5d63fd82e03cb2a0f  drizzle/0011_fia_news.sql
260d0f44448c017772f1e5d793a5d2d840a4e60355d81283c714f908d97de799  drizzle/0012_encrypted_secret_vault.sql
3f90c243d8f982a9e6002335fb079bc51c8858bbf8f3a4f9aafcfd159b2efd2f  drizzle/0013_paper_runs.sql
46e0175a8b07abeaac044fc9a9f58dbafb71348eeb629b90989dc4a1e4a2d941  drizzle/0014_paper_run_idempotency.sql
952038b4db3d06edb35cf9c4d3ba8d6b4fa3c8a43c0c2ea1da6c1ddaafa81266  drizzle/0015_incremental_market_scan.sql
4145c5050b1111e04124a8a85bfccee4804c9860ef10e5a92c427a37edcc2f3f  drizzle/0016_f1_replayable_snapshots.sql
c36a25a2636b560511f7eea28d234d3db14f88386f4bc55e37df12a5f084dfe4  drizzle/0017_deepseek_harness_permission.sql
f2ce42ea1d87a576ab846005a50b4a3a7c0033d70ad01869c5d4a8a19242cb2c  drizzle/0018_probability_decision_engine.sql
e9b9c7549ac58e8cd628528ade52896c8fa3d533728227fdca4e29c67e5ea607  drizzle/0019_probability_integration_fix.sql
870f1adccecf3051cbcd9fd307cef51d7633cf510979c181a81f4b1797273493  eslint.config.mjs
8caa761104fc8ac49256d12f9863db237fa17aa1ba5a59e3813f297d38c67e4d  lib/ai-probability.ts
78c233bdb65ea5ed76e8ece76b92afb2cc236c7de961cf784ffe7e6d5b7a1cd4  lib/client-polling.ts
e845ba171837c233d209ce207eabbc4f678cc882e0e2d60ad135890e127da213  lib/credential-vault.ts
bcf9546712c6a44ad9756ca03c3b7f350952f1993c834549387ff97569e9799e  lib/decision-engine.ts
62e5fc06e8c4ffa2a341953f462676b3d33a88c3cec8835eb29a4a117cd5edfc  lib/encrypted-secret-vault.mjs
b5a1f0ce85ed72f0266e68de5e5e0feac4f84a02c835f28953ecd27f2a946501  lib/expected-value-engine.ts
02f086cc38cde10140a51e836f63d42e6c814337eb04d2ee245df70d57744cd2  lib/f1-feed.ts
cf23aaa5f763b62fc6be4e18078833a422a09466d979fb04a30d2dc984c07646  lib/f1-model.ts
906a368b11ee51e6f55c182e9a71afee92e601b741df9701a6cfdb8ca056416b  lib/fair-value-engine.ts
7b78cc6144fd21564ab50a94528e7e1b930a68d22df6031d03eda134846c291b  lib/kalshi-readonly.ts
7f4eba127cf81de058b7089deb964aeac534ae14b353e2b40ec5c3d03062d17f  lib/learning/daily-review.ts
3c10b2c946c2f2499b987c0be5b413a35f5695738a3c23007356029b6f24ce59  lib/learning/episode-builder.ts
16a093dc7128dde25cf0e1180bd05a387a9ddd19dd998e386fb189889b5c4648  lib/learning/evaluation.d.mts
668f83483f74f397c5b85996259e937bff0514145251af42693e6e9a71b5a47d  lib/learning/evaluation.mjs
017dff545a1648fbb4ff03dd401073651d80ffaa72adf173353a2f83f5ab90b4  lib/learning/job-lock.ts
304a5a6b6688da1ed0aec8287a5bad956d884b04d56fa5922c34c4d9b9186e5a  lib/learning/learning-policy.ts
5911ae295ca9fb2fdc3f3839b1e24dbe3e6b66a3119ff800453a6b4847588b57  lib/learning/profile-registry.ts
818709c589f3523d4f2ebb03c00e5cc5c1f7350f7a5302a2d2f90d61b6676b4a  lib/learning/proposal.d.mts
f2e0ecca22d473e592c1c8ef52c76e5845830610f2e6b0c8e27053d75771d453  lib/learning/proposal.mjs
818f79a786ed93b7053ffd9076729d0b36373081f3bc27dc0a0a2c30c72dac06  lib/learning/scheduler.ts
4ec1159ecfe242f0f10078c02158875ebc57ae08ddc898f602f1aacaf9e54f16  lib/learning/self-reinforcement-guard.d.mts
df81b2ca8ac750ecff6d9fc6d9d3e7aff21cbf865445b37ad5b993b3844e0cef  lib/learning/self-reinforcement-guard.mjs
2ff17018a121639b863e08408be82f803c6504a37ae2394caa2c2e9ef94300c5  lib/learning/time-window.d.mts
133f1e957a6de9b157ca85c5aaa7517ad6e21f456db85b885df82ea4fca05225  lib/learning/time-window.mjs
6a6d299fcbdb0df86b7ce99be7963076db04ae697d1d474cf7c653ed79c91105  lib/market-book.ts
fdaecef1bd5883cf718fba2211f82ee924c109b3dba23ab52bb3746fb6490b93  lib/market-scan.mjs
170712694c7bccfa6dfb7f7d44fa649969ef43a50764c3923babf1f7aeb6d1cc  lib/memory/consolidation.ts
8240b650e0635090dff12a0a78b27123bb1757a43bc6e87996b56c26e4639352  lib/memory/decay.ts
a2664b80d4243102227de3e5ab0309321dc447791ed2545d409d7678e2887112  lib/memory/market-regime.d.mts
404e762a0d89e4da071891e264d2db379bf7dc19cb37f9a7fb67cebe6e99bdac  lib/memory/market-regime.mjs
bab0522c34d0bda5070d8d7fd0613a90dea3fb6b6f574191c69c33ecd3129e38  lib/memory/repository.ts
ae92b716aa20dde29277787abf557cfaadf13b7c9821d70c3ca8453d28b1c6d7  lib/model-credential-validation.ts
970687d300cbeb038d7fddaa5d24cbbd0678dd844b6bcb7ba0de1a5056263dc3  lib/model-review.ts
713f93126b3d1b04d2c799a154c99b5e756aec0cd034a9a2b7dff825acf83332  lib/nws-client.ts
b95a0e47e3465a306d936950d302aa18c33954970bf128c26bc21f9babd8afd0  lib/official-models.ts
77ddadef865f1c7442e88553b16300824a52d727004e61c38ca72b568a1488ad  lib/optimization/engine.ts
ec5da4a45f1c9c439483482a2e41d65aed03d7be01f64d73d39c9c5a0088d2fc  lib/optimization/forward-shadow.ts
d0fe97c1f83b824a808766fc4132a0caa494161f90ae100a3085ea4a4cfc56ee  lib/optimization/parameter-search.d.mts
cfe7a560c1108a56413faacd5fa3b017a61a5c57bbb7a10f53c311067d716627  lib/optimization/parameter-search.mjs
81f928bda45017a0b43ffc85032e5922ab84178d6f1822bae5c9a17b84b506fa  lib/optimization/promotion.d.mts
f81213dc9aaff06f62d0e5c55ce63e9bdfec454f2e034fdc1875dfa02502eeb3  lib/optimization/promotion.mjs
f5eb0946630e72957810203d47e11779d55900d707803fffc373829bba3514b1  lib/optimization/replay-engine.d.mts
ca8677a84ca0bd2b2981f996c78b3c93df563c8d8704822b0b935918484338aa  lib/optimization/replay-engine.mjs
17706172d5c2e149476da47d2e6e04cf35b5f89ece7ae03ee114dbfa2cf95b92  lib/optimization/rollback.ts
d8fe2f62245b8d5b8c8e8d896e25b5744889338ae7b255a15a95e5a06bcac0d0  lib/optimization/shadow-engine.ts
379b1e0a5369a6ba591157bbc33f9ff60910d29caa69995f92f42ebd7c0d785b  lib/optimization/walk-forward.d.mts
5868cd8f8c2d125319624687e34c553b3e0300711f52325c32259fbc328a4497  lib/optimization/walk-forward.mjs
e595ad8164bd2161cc0ef4c1316732a487166be5aa40c1488c1b0259cb8ca955  lib/owner-auth.d.mts
1a83057e000adc809097675157b826bf4b99e550564701dc417f05912b402e9b  lib/owner-auth.mjs
03114fb73f0ac4fab310a6f3606cf40635e0881e770fb4043bdfe76488b51861  lib/paper-core.d.mts
7f4059f374b23256562e12e031299900514c13d29e2075b4280965beb9bf4cfe  lib/paper-core.mjs
650dacc1f7f36d6cb421047b4dcea5537deca22b2d1731d6344c4adce26c40cc  lib/paper-engine.ts
de081c1735674e39d0d575462757487a230bb740e6c165f95da9ae66730d0639  lib/player-rating.ts
704d509a3d1c2a2cfc946d70e9ddbf62dfcb37c3fadbde4e027d20cb50f0d0d1  lib/probability-engine.ts
a84454bcc71dea2b9a179f77ff2b88307e836eda15a79ae9ac1660f18b2720de  lib/risk-adjusted-position-sizing.ts
06da93a65627944c8afd32b7fcb3bc26ec13474d61158507996d588db7950c0e  lib/server.ts
e61a784c1900989410be263830a4bb3e2eb11f624c1134c8f53c060a81651ebe  lib/soft-risk.ts
6e74fbb965e1d5bbe3930be63ddd13a80d3617407854ce5279b15e6f9372546c  lib/sports-data.ts
88e125ff9a9580bfc26fe65e758aa3cbcfd031cac033fee754c565d28b8431be  lib/strategy-profile.ts
1d626b6dffb41d17e17402c70752839bd7e145e5b6c23edaaf3718da0ca6f101  lib/v2/approved-strategies.ts
737d32946f9ddbd6794424289d179b3eb9a010c57faef05fa0a4ea688828d2cf  lib/v2/audit.ts
a8dde77219cc2aff045455298da70a68ee66439594ada05b61c8f4f8b62759f0  lib/v2/bot-control.ts
dac0711ec769fbb904d5590244ac9aef036d975d16a8c2bc044c2523964aa229  lib/v2/calibration.d.mts
b8c150842b22960bdee7355a969954c4d9c4da377eb784a8688f44a3b76b0aed  lib/v2/calibration.mjs
f8fc7f7509c7bc5ab85c2f830f2e9c2f82b16aabbf30eb839e993090686d664e  lib/v2/clock.d.mts
aae3c494301e741c80ed9b47ceeda9be5fa3b88b8656dd229d3bac8762a26c80  lib/v2/clock.mjs
96f8b4cba9192f1fa9b102c536e11bbd50348b96916551f328f069d78367d284  lib/v2/decimal.d.mts
5ed09ea8814a9adc31a2f5b23310ee4a36d5b17635fb7eb63118e50b007f6228  lib/v2/decimal.mjs
31ce4f0d42fa856f7420238538f6c406d1faa09cfba28e65eca5995cbb37289d  lib/v2/engine-support.ts
113a5387b3b2a2d9fbdc0075ed992480132dd29347cc7c1620d0d2338b88fe57  lib/v2/engine.ts
ce6ee8e79fca2e95d4416d9b0fd1ff57acc953caa24cc5e47c1f5229da8569b7  lib/v2/event-spec.d.mts
b2d956599ebd43911778be90441f46c21558c1787d3d9c796132b94983a79e16  lib/v2/event-spec.mjs
b81513e9c8939ec491fbf523381a586ab33895f1f49676379746a1894286ede5  lib/v2/evidence.d.mts
7002379da0b0752a25bd154e5533b12a51e20e2e31c8907a4da26bc202df538d  lib/v2/evidence.mjs
994f751d2a2edf8ad5acd39502bf1729d6c41512fa409b23e817fb444dc73b98  lib/v2/execution-authority.ts
1f45ee7cbf9e9f647c9ffa16d1037da8123f3d781ebc225a6da02dac3a27c7d2  lib/v2/fees.d.mts
0dd22a2082f8d397dd15ff55cb510c9355ec060577a24b662f00be692be36100  lib/v2/fees.mjs
16457a0a628640fd03a85ee68f94c8d9eb0a916ac22f59362d646c0f6fcb03b6  lib/v2/independent-reviewer.ts
d6f0dd222f19a02feedc51dde31d2190f1a1683809b1584a05a49344878fb265  lib/v2/kalshi-websocket.d.mts
16d4ad026830769febcc6c52f6fd0850ba552b085b9012666f240a11e8e31130  lib/v2/kalshi-websocket.mjs
04f710fd11b2844a7a7c1309d2ac1ea93d5e38e96d2c4bad5bfca38e98f406e0  lib/v2/ledger.d.mts
ef263efdb63cbaa987b0f95c2b4170959ecc9e2def96696b5baccf09fe584127  lib/v2/ledger.mjs
f076b32138c0f4a9e8b8344e31a2636eb47b98a9c5ea60f4759b8cd3cd4fa40e  lib/v2/llm-safety.d.mts
e734f45d1328eb247aee2015d37f0ec66277a77fc256664aeb21166e83d9b39d  lib/v2/llm-safety.mjs
de5c2672c753e30b316e78950ee614ffee353c6d7ad6ad7cdb7454750c7a3538  lib/v2/maintenance.ts
f1ee9939f7974f3ff72088dfe5a95fb79c69f5576c1b06f1dbbf0dc5d646c139  lib/v2/mutual-exclusion-executor.ts
40f94590a780acf1ccefcd03458c2f9a180e21a08a9c9f1cd7bd2115e391e256  lib/v2/mutual-exclusion-runtime.ts
e161881efbc1da5ee639f8772eb6b2963b14e402f00393f41dd8e6547942b1e9  lib/v2/official-candidate.ts
3774cf2f93e26c4e468da01ccd866d226ed50a89ae3853d7419a40b06f679263  lib/v2/orderbook.d.mts
3dfa790f55602e4f7880beb8bae091b463661af5e678ffd63c247c8b97719aab  lib/v2/orderbook.mjs
7fb6992e53e7024c0320b65896d0c8a39cc2e25405b6f28b4447852f64acb0b3  lib/v2/paper-ledger.ts
7c2b0bf866febca6052309aa71f946385ea55dc740e7b918e96334d9596e8719  lib/v2/paper-run.ts
6958648f5eea953da9d3d961aa2b8baf1bb407c8a1bd41c37d92ee2c2e86a896  lib/v2/rate-limit.d.mts
5f40d4e4462dd10eca727b36216e67e8359bc20af7920e8bca06e3e6f832ecf6  lib/v2/rate-limit.mjs
384ec6b0b0e6b92cf975376d897bafe16ee8bcdacad0b168927c7649c2c8ab2e  lib/v2/relationship-graph.d.mts
26f934f6ee487e39e4fb1dfdc82f0f45caab5ccbfa4c0126860891b23ba90e18  lib/v2/relationship-graph.mjs
d54178065d7415793bdb84480ce3405415d01799f96429a00cbf46cb93ca5dc8  lib/v2/replay.d.mts
6eee6ac89a0bd5f4a161b0f2ca65933c12015befcaac4341de880289b9fce191  lib/v2/replay.mjs
793e76b908ac49d6a55907479efce30b0625bb90b58ad4bc8e19f65c2af57f82  lib/v2/resting-order-ledger.ts
c938bb95d359c3ba3c794497bad01c4f40ddbe72f209e7d23dd718c6de44e0bf  lib/v2/resting-orders.d.mts
572c40ec0f7f3cf32d09958296515673932f2b91594f87c622c7d20297236cef  lib/v2/resting-orders.mjs
b0814c11ee183c4ff7f393614fc1f3294d4f260e99086f733a1a9f04998046a5  lib/v2/risk.d.mts
2ad964bf0322f7336030f2e237c7ab04565b45464bd4cb20b07fc6557b92027f  lib/v2/risk.mjs
4214a238010b179b0fd9c332dd0bb8469935ed28e3786d217592810cae847fbb  lib/v2/run-lease.ts
42cb5fcf439125d3f6746a77e6d3531bad8fd74d6faad23f9af1c89bc3ef5db3  lib/v2/run-observability.ts
1035e9b3d304e2a7f9ca0c8d94dc85783ff782239c1eca2b1f509b955b92e66a  lib/v2/service-budgets.d.mts
dfc2d9a5da41bf21539793eac7b00a9692d9e805a2a219289dbd8914edc210d6  lib/v2/service-budgets.mjs
43b9b446a8c8a40c64459219acc1c8cd15519086133657bc62af1d3e5a28fd25  lib/v2/settlement.d.mts
454466a5b12227375392c59ac73a30b5e9bd7b4dd1739955fe27d88fe3d47e01  lib/v2/settlement.mjs
72a092fb2142841b813273df2c0ee8b6ec40caf251666a175f0d66ea9d1a55a2  lib/v2/signal.d.mts
62be8758e45ecb7047f895462c75c8ea7dc0aa8d164af456c7be027de5359ab4  lib/v2/signal.mjs
44bb80e6b42cc9394502b7a69c3a9ff2ac64ae8b2d9158e726b1cff42106275d  lib/v2/start-trigger.ts
10796242f34880433abaa0d8de19a3f3413ceab57a96d30703a432f0370878cb  lib/v2/strategies.d.mts
2a490adb998c5910525281e93631d411a13aa2f031cdb3d95f6c94c2ddfe28b5  lib/v2/strategies.mjs
38cb147fffd705869e4d65817f55a420b839339de32343cda26ec3d53790e740  lib/v2/strategy-registry.d.mts
0a25e51d7ce8f10e892edfc40e15c20ed0e2668a9a5e15003ca55d995431de19  lib/v2/strategy-registry.mjs
3e9b21cfd074c93d6a561945640590b6a0fce08afb37f29fa8884c7e24d0f01d  lib/v3/candidate-ranking.mjs
bdb0c7632659a318492dadeddbda4811ac19f70ac3d505744cdd917438323a6e  lib/v3/decision-trace.ts
5d34e9487d3683c60ac46ca60fe957433e13a9791a88eb678da16b4287cdf7bd  lib/v3/recorded-verdict.ts
91c59d4bb23a7e58f7ab929020dc11a6951f70872ebd068e7a6a6691bee213d9  lib/weather-feed.ts
f150e1a7a71a1b2e3fa66226cbaa7ff80bf15f0e1082e3aa4eabb140b1a32ee8  lib/weather-stations.ts
614bce25b089c3f19b1e17a6346c74b858034040154c6621e7d35303004767cc  next.config.ts
957912c7888102e14c28eadb40e6aa55d06503bbfc056b865e681bdb497ce601  package.json
89abd8a345887e30d1a5bcc9d4426fb4d7c0a813e26eab5ddc554299b6250f25  pnpm-lock.yaml
fb4cd1144091d2d15ef21d607c27abe15bc40a45e1b7828ae50e232eabde3e78  pnpm-workspace.yaml
dfac7ac2d86d326a0e5adb024e7943c181393ed17a5fcb8f0315b24c7da6ddde  postcss.config.mjs
e6d2e59b7b5bbb0342e0fb496dfc262decbfe4426bbb7b047aec8d467d1dc6f7  public/favicon.svg
a8c98351cf8071e0de850ae825b38e81320a7654ad8cb6c3c0d1dcedea0e9bb5  public/og-kalshi-paper.png
829d0e3c78b12de6ca77eec03c649c4daaf5c40523c0d1ecd5da658df47f36e5  requirements-fastf1.txt
6527e155fd79e19921c2f2314b9b42ac0a03fbdc7665b70151b71cedf3e235e4  scheduler/worker.ts
8abdea7111a5c09c2d37db1d58cfec81fa1fe7aa89f5974788f08171ec210d40  scheduler/wrangler.jsonc
2234ceddc5e70cf4e2b5d9d5370fc46140c28e3937a1df8310eec1e9eb5b219f  scripts/demo-learning-v3.mjs
21ea87aa7fb9798fb87b6b2b0fc63c1f5cf0b58d16f30acf5c5ce10d75a0a118  scripts/fastf1_ingest.py
2cdbb2bb48aca68e5c85a931a87f3753b83e7c7d44c80312ecf5240ec8972c0e  scripts/fia_news.py
3aa711262289d3066852cf26697a241a3faf029b89e7c5563493be0b52bddf5d  scripts/fia_news_ingest.py
00f80b42b4645c1c8181480e85b77571c4fda150d9ad5e61bccdff9e15727db7  scripts/manual-tick-test.mjs
424050ba1ddfd09670bc891fff816dd131f03707a142e36a99eaee05d0d55142  scripts/replay-v2.mjs
655d73998e377e35b4c9e71174eb8eac69c535eecd658b83aaf91e0b2cf45448  tests/account-initialization.test.mjs
1911649e63903368b12b075c11a6460edb844ce8ee908a14d97da53d7895e636  tests/autonomous-learning-hardening.test.mjs
2b838dccb5320598a034b65ec5defa33503c1796b02a69c3b381e8fb7d48845f  tests/diagnostic-pipeline.test.mjs
0a9644976f7dff57faee6c6da47abc8d31c55fcda5b19b665ee50d0ee0bd2f64  tests/encrypted-secret-vault.test.mjs
4510ec5313dd47b4e2cf04c0e63c7c5926eac466cf976238ace865bf83710f02  tests/official-feeds.test.mjs
1d25044825955e0a8445918c486faac5da5218b2fc8b3ce05a649a66e34a5576  tests/paper-control-routes.test.mjs
b112564f6c0e397035dfde58922b63524d7e8a0635ce22601977ab0eeb5037a9  tests/paper-engine.test.mjs
5c31c9c626d04ec3f3b28fb315539d20dfb75bc7da2e2a2c9f8e8e58ab841e2e  tests/paper-simulation-qa.test.mjs
06d9bc841798d9cd8aa894ce2d486b204302305cdf58de7a7ca2e8d87808f3c9  tests/probability-engine.test.mjs
d3501bd969c5bae954b13219be9160ca6144422049bb87afec214830b357e869  tests/probability-integration-fix.test.mjs
4158300355a0636acfc3d619250c6c3a3223e687e60b451b534ce80b53fc39b8  tests/rendered-html.test.mjs
6c5dc0c6312c134c27f8043f90a65c071a8260d8d95f9797116fb951f6dc1384  tests/server-safety.test.mjs
9a172a4d03450c86a0041dc6f517ec3ea18a3b23bf3f84f6dc97b5c2be836168  tests/sports-data-atomic.test.mjs
c0b083bbcc4f01c33586e033d1f9b9ea6d87dd8e3b1b7aeab11a412dd35b176a  tests/sports-trading.test.mjs
3478762d330bde0c9a28712151c88c8a5221ac36f730d0a50c457a48a0a2c352  tests/test_fia_news.py
22f5ad36020e65ff15aa4b5cd04bc72afa2e365c64d9e01b6cb657266021cb65  tests/v2-chaos.test.mjs
b26a563af03d1aecadcbfebf33c22c58a11b505b31c74cd33590d603b0320df4  tests/v2-domain.test.mjs
4bb96dbb3eac0beb409d9d5a863ea987bddaec6ef8860c3948861e801781ddc3  tests/v2-security.test.mjs
085d9dcd0c25905ad9cffdc0a5cb7b833f1a55568b3328404f704af14ef1fd99  tests/v2-sqlite-integration.test.mjs
a9fb4260dccdff0375756decb184a5bd9f496ca279a2bad0d94d26d406ae7bac  tests/v3-daily-review-integration.test.mjs
8f0d6e219b1c85df617c12cdd599af41d0409428748344c0e58786e1a5d0d134  tests/v3-f1-pipeline.test.mjs
fc581c83034da1c8262515f6ee926e83454742e13c2cbd16ea242f517da8cb7e  tests/v3-learning-domain.test.mjs
cba89722aa4d2d9385657bb7360e8b37cfe0ebf71302e48d7118c5ac367d4ab5  tests/v3-learning-scheduler.test.mjs
b692210da3230998c31e55e94ef4b5f17b0498d17d97a3d9029b0b2de34927b7  tests/v3-memory-integration.test.mjs
b803543631662817d5e5cf0a3598830a171c0dc1b18732bab532af88eec8f67f  tests/v3-optimization-integration.test.mjs
2fdc19da0aaa07cbada88b8a9623bd50b920cfd7f6f1ee3ac6be398bb53ee8e7  tests/v3-rollback-integration.test.mjs
0433593998fbbd93524aa8ba1ed049708a56ad8d06427fbd31106239ef5ebe5d  tests/v3-runtime-safety.test.mjs
6328fda6d13703e2da5ef49949d3f4e18a91eef9202065c734ef35359699840e  tests/v3-schema-parity.test.mjs
4bf9e8832c184f32089343b604ce636cdf590f49faa7069499954f71326bb24c  tests/v3-weekly-consolidation.test.mjs
9b92cfa2e569828f8b7d14e89beadc88b56085d283976a571ca022aea0c8da23  tsconfig.json
7f2e4956bd5684b32fd0104200f8d4e0b8c12a6b615ebb9f9332031318bfbeaa  vite.config.ts
5785dcc71d48d9a157e5306fe623310d62f4465d0c3a42aaf201856d30ff8208  worker/index.ts
```

## 4. AFTER-BUILD VERIFICATION (SOURCE_REPOS_BEFORE == SOURCE_REPOS_AFTER)

Verified at completion time (2026-08-24 UTC) by recomputing sha256 manifests and git status.

- SilverQuant full-file sha256 manifest: **IDENTICAL** (251 files)
- Kalshi v1 full-worktree sha256 manifest: **IDENTICAL** (266 entries)
- Kalshi v2 full-worktree sha256 manifest: **IDENTICAL** (254 entries)
- Kalshi v1 `git status --porcelain`: same two pre-existing untracked files, no new changes
- Kalshi v2 `git status --porcelain`: still empty
- Kalshi v1 HEAD: `fadb6dd2ab7767829948d2ce7a9c5f49bf392c85` (unchanged)
- Kalshi v2 HEAD: `7cc5d25ca770be03e4098cdcc1b5da38659a398c` (unchanged)

Conclusion:
- SilverQuant modified: NO
- Kalshi v1 modified: NO
- Kalshi v2 modified: NO
