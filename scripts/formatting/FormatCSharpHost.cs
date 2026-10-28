using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;

internal static class FormatCSharpHost
{
    private sealed class FilePair
    {
        public string RelativePath { get; set; } = "";
        public string OriginalPath { get; set; } = "";
        public string CandidatePath { get; set; } = "";
    }

    private static readonly string[][] SymbolModes =
    {
        Array.Empty<string>(),
        new[]
        {
            "UNITY_EDITOR",
            "UNITY_INCLUDE_TESTS"
        },
        new[]
        {
            "UNITY_EDITOR",
            "UNITY_INCLUDE_TESTS",
            "ROS2"
        },
        new[]
        {
            "ROS2"
        },
    };
    private static SyntaxNode Parse(string path, string[] symbols)
    {
        var options = new CSharpParseOptions(LanguageVersion.CSharp9).WithPreprocessorSymbols(symbols);
        var tree = CSharpSyntaxTree.ParseText(File.ReadAllText(path), options, path);
        var errors = tree.GetDiagnostics().Where(diagnostic => diagnostic.Severity == DiagnosticSeverity.Error).ToArray();
        if (errors.Length != 0)
        {
            throw new InvalidDataException(path + ": " + string.Join("; ", errors.Select(error => error.ToString())));
        }

        return tree.GetRoot();
    }

    private static string[] Comments(SyntaxNode root)
    {
        // Structured XML documentation is covered by the strict token comparison;
        // allow its formatter to adjust attribute whitespace around '='.
        return root.DescendantTrivia(descendIntoTrivia: true).Where(trivia => trivia.IsKind(SyntaxKind.SingleLineCommentTrivia) || trivia.IsKind(SyntaxKind.MultiLineCommentTrivia)).Select(trivia => string.Join("\n", trivia.ToFullString().Replace("\r\n", "\n").Split('\n').Select(line => line.Trim())).Trim()).ToArray();
    }

    private static void Verify(FilePair pair)
    {
        foreach (var symbols in SymbolModes)
        {
            var before = Parse(pair.OriginalPath, symbols);
            var after = Parse(pair.CandidatePath, symbols);
            var beforeTokens = before.DescendantTokens(descendIntoTrivia: true).Select(token => (token.RawKind, token.Text));
            var afterTokens = after.DescendantTokens(descendIntoTrivia: true).Select(token => (token.RawKind, token.Text));
            if (!beforeTokens.SequenceEqual(afterTokens))
            {
                throw new InvalidDataException("C# token/directive mismatch: " + pair.RelativePath + " [" + string.Join(",", symbols) + "]");
            }

            if (!Comments(before).SequenceEqual(Comments(after)))
            {
                throw new InvalidDataException("C# comment content mismatch: " + pair.RelativePath);
            }
        }
    }

    public static int Main(string[] args)
    {
        try
        {
            if (args.Length != 2 || !new[]
            {
                "normalize",
                "verify"
            }.Contains(args[0]))
            {
                throw new ArgumentException("Expected normalize/verify and a private file inventory.");
            }

            var pairs = JsonSerializer.Deserialize<FilePair[]>(File.ReadAllText(args[1]));
            if (pairs == null || pairs.Length == 0)
            {
                throw new InvalidDataException("No C# files in the private inventory.");
            }

            foreach (var pair in pairs)
            {
                if (args[0] == "normalize")
                {
                    var original = Parse(pair.OriginalPath, SymbolModes[1]);
                    var formatted = original.NormalizeWhitespace("    ", "\n", false).ToFullString().TrimEnd() + "\n";
                    Directory.CreateDirectory(Path.GetDirectoryName(pair.CandidatePath));
                    File.WriteAllText(pair.CandidatePath, formatted, new UTF8Encoding(false));
                }

                Verify(pair);
            }

            Console.WriteLine("PASS: " + pairs.Length + " C# files; tokens, directives and comments " + "preserved in four editor/tests/ROS2 symbol modes.");
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.Message);
            return 2;
        }
    }
}
