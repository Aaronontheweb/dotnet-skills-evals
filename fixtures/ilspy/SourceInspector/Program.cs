using System.IO.Compression;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Text.Json;

// Reads debug metadata only. It never loads or executes the inspected assembly.
try
{
    if (args.Length == 0)
        throw new ArgumentException("Usage: SourceInspector assembly [--pdb path] [--document name] [--offset n]");
    var assemblyPath = Path.GetFullPath(args[0]);
    string? externalPdb = null;
    string? requestedDocument = null;
    var offset = 0;
    for (var i = 1; i < args.Length; i += 2)
    {
        if (i + 1 == args.Length)
            throw new ArgumentException($"Missing value for {args[i]}");
        switch (args[i])
        {
            case "--pdb": externalPdb = Path.GetFullPath(args[i + 1]); break;
            case "--document": requestedDocument = args[i + 1]; break;
            case "--offset": offset = int.Parse(args[i + 1]); break;
            default: throw new ArgumentException($"Unknown option {args[i]}");
        }
    }
    if (offset < 0)
        throw new ArgumentOutOfRangeException(nameof(offset));
    using var assemblyStream = File.OpenRead(assemblyPath);
    using var pe = new PEReader(assemblyStream);
    var symbolKeys = new List<string>();
    foreach (var entry in pe.ReadDebugDirectory())
    {
        if (entry.Type != DebugDirectoryEntryType.CodeView || !entry.IsPortableCodeView)
            continue;
        var data = pe.ReadCodeViewDebugDirectoryData(entry);
        var name = Path.GetFileName(data.Path.Replace('\\', '/'));
        symbolKeys.Add($"{name}/{data.Guid:N}FFFFFFFF/{name}");
    }
    // PEReader validates that the supplied Portable PDB belongs to this PE.
    var found = pe.TryOpenAssociatedPortablePdb(assemblyPath,
        path => File.Exists(externalPdb ?? path) ? File.OpenRead(externalPdb ?? path) : null,
        out var provider, out var pdbPath);
    using (provider)
    {
        if (externalPdb is not null && !found)
            throw new BadImageFormatException("The supplied PDB does not match the assembly.");
        var mappings = new Dictionary<string, string>();
        var documents = new List<SourceDocument>();
        byte[]? embeddedSource = null;
        if (found && provider is not null)
        {
            var reader = provider.GetMetadataReader();
            foreach (var handle in reader.CustomDebugInformation)
            {
                var info = reader.GetCustomDebugInformation(handle);
                if (info.Parent.Kind != HandleKind.ModuleDefinition ||
                    reader.GetGuid(info.Kind) != new Guid("cc110556-a091-4d38-9fec-25ab9a351a6a"))
                    continue;
                using var json = JsonDocument.Parse(reader.GetBlobBytes(info.Value));
                foreach (var item in json.RootElement.GetProperty("documents").EnumerateObject())
                    mappings.Add(item.Name, item.Value.GetString() ?? throw new BadImageFormatException("Null source URL"));
            }
            foreach (var handle in reader.Documents)
            {
                var doc = reader.GetDocument(handle);
                var name = reader.GetString(doc.Name);
                var hasEmbeddedSource = false;
                foreach (var debugHandle in reader.GetCustomDebugInformation(handle))
                {
                    var info = reader.GetCustomDebugInformation(debugHandle);
                    if (reader.GetGuid(info.Kind) != new Guid("0e8a571b-6926-466e-b4ad-8ab04611f5fe"))
                        continue;
                    hasEmbeddedSource = true;
                    if (name == requestedDocument)
                        embeddedSource = ReadEmbedded(reader.GetBlobBytes(info.Value));
                }
                documents.Add(new SourceDocument(name,
                    doc.HashAlgorithm.IsNil ? null : reader.GetGuid(doc.HashAlgorithm).ToString(),
                    Convert.ToHexString(reader.GetBlobBytes(doc.Hash)).ToLowerInvariant(), hasEmbeddedSource));
            }
        }
        var selected = requestedDocument is null
            ? documents.Skip(offset).Take(50).ToArray()
            : documents.Where(d => d.Name == requestedDocument).ToArray();
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            Assembly = assemblyPath, PdbFound = found, PdbPath = pdbPath,
            SymbolKeys = symbolKeys, Mappings = mappings, Documents = selected,
            TotalDocuments = documents.Count,
            NextOffset = requestedDocument is null && offset + selected.Length < documents.Count
                ? (int?)(offset + selected.Length) : null,
            EmbeddedSource = embeddedSource
        }, new JsonSerializerOptions(JsonSerializerDefaults.Web)));
    }
    return 0;
}
catch (Exception error) when (error is IOException or BadImageFormatException or ArgumentException
                            or JsonException or FormatException or OverflowException)
{
    Console.Error.WriteLine(JsonSerializer.Serialize(new { error = error.Message }));
    return 1;
}

static byte[] ReadEmbedded(byte[] blob)
{
    if (blob.Length < 4)
        throw new BadImageFormatException("Truncated embedded source");
    var size = System.Buffers.Binary.BinaryPrimitives.ReadInt32LittleEndian(blob);
    if (size == 0)
        return blob[4..];
    if (size < 0 || size > 4 * 1024 * 1024)
        throw new BadImageFormatException("Embedded source exceeds the 4 MiB limit");
    using var input = new MemoryStream(blob, 4, blob.Length - 4);
    using var decompressor = new DeflateStream(input, CompressionMode.Decompress);
    var output = new byte[size];
    decompressor.ReadExactly(output);
    if (decompressor.ReadByte() != -1)
        throw new BadImageFormatException("Embedded source length mismatch");
    return output;
}

internal sealed record SourceDocument(string Name, string? HashAlgorithm, string Checksum, bool Embedded);
