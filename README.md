### Royce Payroll Ke

Kenya PAYE, NSSF, SHIF and Housing Levy payroll compliance engine for ERPNext

### Documentation

- [`docs/user-guide.md`](docs/user-guide.md) — how to actually run this: creating a Payroll
  Rates record, provisioning a company, assigning employees, updating rates.
- [`docs/architecture.md`](docs/architecture.md) — why it's built this way: decisions, data
  model, open questions.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch version-16
bench install-app royce_payroll_ke
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/royce_payroll_ke
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
