// A small JSON reader and writer, so the extension needs no library.
// Objects are Dictionary<string, object>, arrays are List<object>, numbers are long or
// double, plus string, bool and null.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace AutoDebug
{
    public static class Json
    {
        public static object Parse(string text)
        {
            var reader = new Reader(text);
            reader.Space();
            var value = reader.Value();
            reader.Space();
            if (!reader.Done) throw new FormatException("unexpected text after the JSON value");
            return value;
        }

        public static string Write(object value, bool indent = false)
        {
            var output = new StringBuilder();
            Emit(output, value, indent ? 0 : -1);
            return output.ToString();
        }

        // -- typed access ---------------------------------------------------------------

        public static Dictionary<string, object> Obj(object value) => value as Dictionary<string, object> ?? new Dictionary<string, object>();

        public static List<object> List(object value) => value as List<object> ?? new List<object>();

        public static object Get(Dictionary<string, object> obj, string key) => obj != null && obj.TryGetValue(key, out var value) ? value : null;

        public static string Str(Dictionary<string, object> obj, string key) => Get(obj, key) as string;

        public static long? Long(Dictionary<string, object> obj, string key)
        {
            switch (Get(obj, key))
            {
                case long l: return l;
                case double d when Math.Abs(d % 1) < 1e-9: return (long)d;
                default: return null;
            }
        }

        public static Dictionary<string, object> Make(params object[] pairs)
        {
            var obj = new Dictionary<string, object>();
            for (var i = 0; i + 1 < pairs.Length; i += 2) obj[(string)pairs[i]] = pairs[i + 1];
            return obj;
        }

        // -- writing --------------------------------------------------------------------

        static void Emit(StringBuilder output, object value, int depth)
        {
            switch (value)
            {
                case null: output.Append("null"); break;
                case bool b: output.Append(b ? "true" : "false"); break;
                case string s: Quote(output, s); break;
                case int or long or short or uint or ulong: output.Append(Convert.ToString(value, CultureInfo.InvariantCulture)); break;
                case double or float or decimal:
                    output.Append(Convert.ToDouble(value, CultureInfo.InvariantCulture).ToString("R", CultureInfo.InvariantCulture));
                    break;
                case IDictionary<string, object> obj:
                    output.Append('{');
                    var firstKey = true;
                    foreach (var pair in obj)
                    {
                        if (!firstKey) output.Append(',');
                        firstKey = false;
                        if (depth >= 0) Newline(output, depth + 1);
                        Quote(output, pair.Key);
                        output.Append(depth >= 0 ? ": " : ":");
                        Emit(output, pair.Value, depth < 0 ? -1 : depth + 1);
                    }
                    if (!firstKey && depth >= 0) Newline(output, depth);
                    output.Append('}');
                    break;
                case System.Collections.IEnumerable list:
                    output.Append('[');
                    var firstItem = true;
                    foreach (var item in list)
                    {
                        if (!firstItem) output.Append(',');
                        firstItem = false;
                        if (depth >= 0) Newline(output, depth + 1);
                        Emit(output, item, depth < 0 ? -1 : depth + 1);
                    }
                    if (!firstItem && depth >= 0) Newline(output, depth);
                    output.Append(']');
                    break;
                default: Quote(output, Convert.ToString(value, CultureInfo.InvariantCulture)); break;
            }
        }

        static void Newline(StringBuilder output, int depth)
        {
            if (depth < 0) return;
            output.Append('\n').Append(' ', depth * 2);
        }

        static void Quote(StringBuilder output, string text)
        {
            output.Append('"');
            foreach (var c in text)
            {
                switch (c)
                {
                    case '"': output.Append("\\\""); break;
                    case '\\': output.Append("\\\\"); break;
                    case '\n': output.Append("\\n"); break;
                    case '\r': output.Append("\\r"); break;
                    case '\t': output.Append("\\t"); break;
                    default:
                        if (c < 0x20) output.Append("\\u").Append(((int)c).ToString("x4"));
                        else output.Append(c);
                        break;
                }
            }
            output.Append('"');
        }

        // -- reading --------------------------------------------------------------------

        sealed class Reader
        {
            readonly string text;
            int at;
            int depth;

            public Reader(string text) { this.text = text ?? ""; }

            public bool Done => at >= text.Length;

            public void Space()
            {
                while (at < text.Length && char.IsWhiteSpace(text[at])) at++;
            }

            char Peek() => at < text.Length ? text[at] : '\0';

            void Expect(char c)
            {
                if (Peek() != c) throw new FormatException($"expected '{c}' at {at}");
                at++;
            }

            public object Value()
            {
                if (++depth > 64) throw new FormatException("JSON nested too deeply");
                try
                {
                    switch (Peek())
                    {
                        case '{': return Object();
                        case '[': return Array();
                        case '"': return String();
                        case 't': Word("true"); return true;
                        case 'f': Word("false"); return false;
                        case 'n': Word("null"); return null;
                        default: return Number();
                    }
                }
                finally { depth--; }
            }

            void Word(string word)
            {
                if (string.CompareOrdinal(text, at, word, 0, word.Length) != 0) throw new FormatException($"bad value at {at}");
                at += word.Length;
            }

            Dictionary<string, object> Object()
            {
                var obj = new Dictionary<string, object>();
                Expect('{');
                Space();
                if (Peek() == '}') { at++; return obj; }
                while (true)
                {
                    Space();
                    var key = String();
                    Space();
                    Expect(':');
                    Space();
                    obj[key] = Value();
                    Space();
                    if (Peek() == ',') { at++; continue; }
                    Expect('}');
                    return obj;
                }
            }

            List<object> Array()
            {
                var list = new List<object>();
                Expect('[');
                Space();
                if (Peek() == ']') { at++; return list; }
                while (true)
                {
                    Space();
                    list.Add(Value());
                    Space();
                    if (Peek() == ',') { at++; continue; }
                    Expect(']');
                    return list;
                }
            }

            string String()
            {
                Expect('"');
                var output = new StringBuilder();
                while (true)
                {
                    if (Done) throw new FormatException("unterminated string");
                    var c = text[at++];
                    if (c == '"') return output.ToString();
                    if (c != '\\') { output.Append(c); continue; }
                    if (Done) throw new FormatException("unterminated string");
                    var e = text[at++];
                    switch (e)
                    {
                        case '"': output.Append('"'); break;
                        case '\\': output.Append('\\'); break;
                        case '/': output.Append('/'); break;
                        case 'b': output.Append('\b'); break;
                        case 'f': output.Append('\f'); break;
                        case 'n': output.Append('\n'); break;
                        case 'r': output.Append('\r'); break;
                        case 't': output.Append('\t'); break;
                        case 'u':
                            if (at + 4 > text.Length) throw new FormatException("bad escape");
                            output.Append((char)int.Parse(text.Substring(at, 4), NumberStyles.HexNumber, CultureInfo.InvariantCulture));
                            at += 4;
                            break;
                        default: throw new FormatException("bad escape");
                    }
                }
            }

            object Number()
            {
                var start = at;
                if (Peek() == '-') at++;
                while (at < text.Length && "0123456789+-.eE".IndexOf(text[at]) >= 0) at++;
                var token = text.Substring(start, at - start);
                if (token.Length == 0) throw new FormatException($"bad value at {start}");
                if (long.TryParse(token, NumberStyles.Integer, CultureInfo.InvariantCulture, out var whole)) return whole;
                return double.Parse(token, NumberStyles.Float, CultureInfo.InvariantCulture);
            }
        }
    }
}
