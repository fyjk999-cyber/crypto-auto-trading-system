# FACTOR SYSTEM REFACTOR AUDIT

|Module|Classification|Action|
|-|-|-|
|factors/capture.py|KEEP|Reuse behind FactorToolGateway|
|factors/engine.py|KEEP|Reuse|
|factors/registry.py|KEEP|Reuse|
|factors/catalog.py|KEEP|Reuse|
|factors/models.py|ADAPT|Add immutable versioned snapshot contract|
|factors/service.py|ADAPT|Snapshot persistence|
|factors/attribution.py|KEEP|Daily learning attribution|
|factors/decay.py|KEEP|Reviewer/evolver|
|factors/evaluator.py|KEEP|Reviewer|
|factors/confidence.py|KEEP|Live consumer|
|factors/analytics.py|KEEP|Monthly/yearly reviewer|
|factors/discovery.py|ADAPT|Evolution provider|
|factors/experiment.py|KEEP|Evolution validation|
|factors/combinations/|KEEP|Evolution candidate|
|factors/anomaly/|KEEP|Daily/weekly review signal|
|alpha_decay/|ADAPT|Evidence provider|
|alpha_discovery/|ADAPT|Evolution provider|
|alpha_intelligence/|ADAPT|Reviewer|
|evolution/factor_evolution.py|KEEP|Evolution core|
|factors/lifecycle/|KEEP|Evolution state|
|factors/importance.py|KEEP|Reviewer|
