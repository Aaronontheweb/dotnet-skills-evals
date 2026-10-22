using System.Text.Json;
using Petabridge.Cmd;

var echo = new CommandDefinitionBuilder()
    .WithName("echo")
    .WithDescription("Echoes the supplied support message")
    .WithArgument(argument => argument.WithName("message")
        .WithSwitch("-m").IsMandatory(true))
    .Build();
var parser = new CommandParser(new CommandPalette("ops", new[] { echo }));

string[] examples = args.Length == 0
    ? ["ops echo -m \"plain text\"", "ops echo -m \"'blue team'\"",
        "ops echo -m \"say \\\"hello\\\"\""]
    : [string.Join(" ", args)];

foreach (var line in examples)
{
    var result = parser.Parse(line);
    Console.WriteLine($"Input: {JsonSerializer.Serialize(line)}");
    Console.WriteLine($"Success: {result.Success}");
    if (result.Success)
        foreach (var argument in result.Result.Arguments)
            Console.WriteLine($"Handler receives: {JsonSerializer.Serialize(argument.Item2)}");
    else
        foreach (var error in result.ParseErrors)
            Console.WriteLine($"Validation: {error}");
    Console.WriteLine();
}
