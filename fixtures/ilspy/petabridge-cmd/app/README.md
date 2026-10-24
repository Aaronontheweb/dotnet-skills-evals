# Support console

This small application defines our `ops echo -m` support command and prints what
the handler would receive after parsing the input line.

Run the prepared application from the repository directory:

```bash
dotnet bin/Release/net10.0/SupportConsole.dll
```

To make changes, copy the checkout into `/tmp`, then build there. The restored
NuGet packages are available in the package cache; an offline restore can use
`dotnet restore --source "$NUGET_PACKAGES" -p:NuGetAudit=false`.
