// Image Studio.exe: starts the desktop app with the Python bundled next to it.
// Built by packaging/build.py with the C# compiler that ships with Windows (.NET Framework 4).

using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

static class Launcher
{
    const string Title = "Image Studio";
    const int WatchMilliseconds = 8000;  // a start-up failure shows within this

    [STAThread]
    static int Main(string[] args)
    {
        string folder = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(folder, "runtime", "pythonw.exe");
        if (!File.Exists(python))
        {
            Show("Image Studio is incomplete: " + python + " is missing. Reinstall it to fix this.");
            return 1;
        }
        StringBuilder arguments = new StringBuilder("-m image_studio.desktop");
        foreach (string arg in args)
        {
            arguments.Append(' ').Append(Quote(arg));
        }
        ProcessStartInfo start = new ProcessStartInfo(python, arguments.ToString());
        start.UseShellExecute = false;
        start.WorkingDirectory = folder;
        // A Python set up elsewhere on this PC must not leak into the bundled one.
        start.EnvironmentVariables.Remove("PYTHONHOME");
        start.EnvironmentVariables.Remove("PYTHONPATH");
        start.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
        Process app;
        try
        {
            app = Process.Start(start);
        }
        catch (Exception error)
        {
            Show("Image Studio could not start: " + error.Message);
            return 1;
        }
        if (app.WaitForExit(WatchMilliseconds) && app.ExitCode != 0)
        {
            string log = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                      "Image Studio", "logs", "app.log");
            Show("Image Studio closed while starting. The details are in " + log + ".");
            return app.ExitCode;
        }
        return 0;
    }

    static void Show(string text)
    {
        MessageBox.Show(text, Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
    }

    static string Quote(string arg)
    {
        if (arg.Length > 0 && arg.IndexOfAny(new[] { ' ', '\t', '"' }) < 0)
        {
            return arg;
        }
        StringBuilder quoted = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in arg)
        {
            if (c == '\\')
            {
                slashes++;
                continue;
            }
            quoted.Append('\\', c == '"' ? slashes * 2 + 1 : slashes);
            slashes = 0;
            quoted.Append(c);
        }
        quoted.Append('\\', slashes * 2).Append('"');
        return quoted.ToString();
    }
}
