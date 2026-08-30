using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace VoiceMasterLauncher
{
    internal static class Program
    {
        private const string Repository = "aminechaff/voice_detection";
        private const string Branch = "main";
        private const string UserAgent = "VoiceMaster-Windows-Launcher";

        private static readonly string InstallDirectory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "VoiceMaster");
        private static readonly string AppDirectory = Path.Combine(InstallDirectory, "app");
        private static readonly string EnvironmentDirectory = Path.Combine(InstallDirectory, ".venv");
        private static readonly string InstalledLauncher = Path.Combine(
            InstallDirectory, "Voice Master.exe");
        private static readonly string VersionFile = Path.Combine(InstallDirectory, "version.txt");
        private static readonly string UvExecutable = Path.Combine(InstallDirectory, "uv.exe");

        [STAThread]
        private static void Main()
        {
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            if (InstallLauncher())
            {
                return;
            }

            Application.Run(new LauncherWindow());
        }

        private static bool InstallLauncher()
        {
            string current = Path.GetFullPath(Application.ExecutablePath);
            string installed = Path.GetFullPath(InstalledLauncher);
            if (string.Equals(current, installed, StringComparison.OrdinalIgnoreCase))
            {
                EnsureShortcut();
                return false;
            }

            try
            {
                Directory.CreateDirectory(InstallDirectory);
                File.Copy(current, installed, true);
                EnsureShortcut();
                Process.Start(new ProcessStartInfo
                {
                    FileName = installed,
                    UseShellExecute = true,
                    WorkingDirectory = InstallDirectory
                });
                return true;
            }
            catch (Exception exception)
            {
                MessageBox.Show(
                    "Impossible d'installer Voice Master.\n\n" + exception.Message,
                    "Voice Master",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
                return true;
            }
        }

        private static void EnsureShortcut()
        {
            string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
            string shortcutPath = Path.Combine(desktop, "Voice Master.lnk");
            Type shellType = Type.GetTypeFromProgID("WScript.Shell");
            if (shellType == null)
            {
                return;
            }

            dynamic shell = Activator.CreateInstance(shellType);
            dynamic shortcut = shell.CreateShortcut(shortcutPath);
            shortcut.TargetPath = InstalledLauncher;
            shortcut.WorkingDirectory = InstallDirectory;
            shortcut.IconLocation = InstalledLauncher + ",0";
            shortcut.Description = "Transcription locale du microphone et du son du PC";
            shortcut.Save();
        }

        private sealed class LauncherWindow : Form
        {
            private readonly Label title;
            private readonly Label status;
            private readonly ProgressBar progress;

            internal LauncherWindow()
            {
                Text = "Voice Master";
                ClientSize = new Size(460, 190);
                StartPosition = FormStartPosition.CenterScreen;
                FormBorderStyle = FormBorderStyle.FixedSingle;
                MaximizeBox = false;
                BackColor = Color.FromArgb(10, 18, 38);
                ForeColor = Color.White;
                Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);

                title = new Label
                {
                    Text = "VOICE MASTER",
                    Font = new Font("Segoe UI Semibold", 18F, FontStyle.Bold),
                    ForeColor = Color.White,
                    AutoSize = true,
                    Location = new Point(28, 25)
                };
                status = new Label
                {
                    Text = "Préparation…",
                    Font = new Font("Segoe UI", 10F),
                    ForeColor = Color.FromArgb(177, 190, 216),
                    AutoEllipsis = true,
                    Location = new Point(31, 87),
                    Size = new Size(396, 25)
                };
                progress = new ProgressBar
                {
                    Style = ProgressBarStyle.Marquee,
                    MarqueeAnimationSpeed = 28,
                    Location = new Point(32, 126),
                    Size = new Size(395, 8)
                };

                Controls.Add(title);
                Controls.Add(status);
                Controls.Add(progress);
                Shown += OnShown;
            }

            private async void OnShown(object sender, EventArgs eventArgs)
            {
                try
                {
                    await Task.Run((Action)PrepareAndLaunch);
                    CloseSafely();
                }
                catch (Exception exception)
                {
                    progress.Invoke((Action)(() => progress.Style = ProgressBarStyle.Blocks));
                    MessageBox.Show(
                        this,
                        "Voice Master n'a pas pu démarrer.\n\n" + exception.Message,
                        "Voice Master",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error);
                    CloseSafely();
                }
            }

            private void PrepareAndLaunch()
            {
                Directory.CreateDirectory(InstallDirectory);
                string localVersion = File.Exists(VersionFile)
                    ? File.ReadAllText(VersionFile).Trim()
                    : string.Empty;
                string remoteVersion = null;

                SetStatus("Recherche d'une mise à jour…");
                try
                {
                    remoteVersion = GetRemoteVersion();
                }
                catch (Exception)
                {
                    if (!IsApplicationReady())
                    {
                        throw new InvalidOperationException(
                            "Une connexion Internet est nécessaire pour la première installation.");
                    }
                }

                if (!IsApplicationReady() ||
                    (!string.IsNullOrEmpty(remoteVersion) && remoteVersion != localVersion))
                {
                    InstallApplication(remoteVersion);
                }

                SetStatus("Ouverture de Voice Master…");
                StartApplication();
            }

            private void InstallApplication(string remoteVersion)
            {
                string temporaryRoot = Path.Combine(
                    Path.GetTempPath(), "VoiceMaster-" + Guid.NewGuid().ToString("N"));
                string archivePath = Path.Combine(temporaryRoot, "source.zip");
                string extractedPath = Path.Combine(temporaryRoot, "source");
                string stagedApp = Path.Combine(InstallDirectory, "app-new");
                string previousApp = Path.Combine(InstallDirectory, "app-old");

                try
                {
                    Directory.CreateDirectory(temporaryRoot);
                    SetStatus("Téléchargement de la dernière version…");
                    DownloadFile(
                        "https://github.com/" + Repository + "/archive/refs/heads/" + Branch + ".zip",
                        archivePath);

                    SetStatus("Préparation de l'application…");
                    ZipFile.ExtractToDirectory(archivePath, extractedPath);
                    string sourceRoot = Directory.GetDirectories(extractedPath).Single();

                    DeleteDirectory(stagedApp);
                    CopyDirectory(sourceRoot, stagedApp);
                    DeleteDirectory(previousApp);
                    if (Directory.Exists(AppDirectory))
                    {
                        Directory.Move(AppDirectory, previousApp);
                    }
                    Directory.Move(stagedApp, AppDirectory);

                    EnsureUv(temporaryRoot);
                    EnsurePythonEnvironment();
                    SetStatus("Installation des composants…");
                    RunUv(
                        "pip install --quiet --upgrade --python " + Quote(PythonExecutable()) +
                        " " + Quote(AppDirectory));

                    RunPython("-c \"import customtkinter, faster_whisper, pyaudiowpatch, voicemaster\"");
                    File.WriteAllText(
                        VersionFile,
                        string.IsNullOrEmpty(remoteVersion) ? DateTime.UtcNow.Ticks.ToString() : remoteVersion);
                    DeleteDirectory(previousApp);
                }
                catch
                {
                    DeleteDirectory(AppDirectory);
                    if (Directory.Exists(previousApp))
                    {
                        Directory.Move(previousApp, AppDirectory);
                    }
                    throw;
                }
                finally
                {
                    DeleteDirectory(stagedApp);
                    DeleteDirectory(temporaryRoot);
                }
            }

            private void EnsureUv(string temporaryRoot)
            {
                if (File.Exists(UvExecutable))
                {
                    return;
                }

                SetStatus("Installation du gestionnaire Python…");
                string uvArchive = Path.Combine(temporaryRoot, "uv.zip");
                string uvExtracted = Path.Combine(temporaryRoot, "uv");
                DownloadFile(
                    "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip",
                    uvArchive);
                ZipFile.ExtractToDirectory(uvArchive, uvExtracted);
                string downloadedUv = Directory.GetFiles(uvExtracted, "uv.exe", SearchOption.AllDirectories)
                    .Single();
                File.Copy(downloadedUv, UvExecutable, true);
            }

            private void EnsurePythonEnvironment()
            {
                if (File.Exists(PythonExecutable()))
                {
                    return;
                }

                SetStatus("Installation de Python 3.11…");
                RunUv("venv " + Quote(EnvironmentDirectory) + " --python 3.11");
            }

            private static string GetRemoteVersion()
            {
                string json = DownloadText(
                    "https://api.github.com/repos/" + Repository + "/commits/" + Branch);
                Match match = Regex.Match(json, "\\\"sha\\\"\\s*:\\s*\\\"([0-9a-f]{40})\\\"");
                if (!match.Success)
                {
                    throw new InvalidDataException("Réponse GitHub non reconnue.");
                }
                return match.Groups[1].Value;
            }

            private static string DownloadText(string address)
            {
                using (WebClient client = CreateWebClient())
                {
                    return client.DownloadString(address);
                }
            }

            private static void DownloadFile(string address, string destination)
            {
                using (WebClient client = CreateWebClient())
                {
                    client.DownloadFile(address, destination);
                }
            }

            private static WebClient CreateWebClient()
            {
                WebClient client = new WebClient();
                client.Headers.Add(HttpRequestHeader.UserAgent, UserAgent);
                return client;
            }

            private static void RunUv(string arguments)
            {
                RunProcess(UvExecutable, arguments);
            }

            private static void RunPython(string arguments)
            {
                RunProcess(PythonExecutable(), arguments);
            }

            private static void RunProcess(string executable, string arguments)
            {
                ProcessStartInfo startInfo = new ProcessStartInfo
                {
                    FileName = executable,
                    Arguments = arguments,
                    WorkingDirectory = InstallDirectory,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                };
                startInfo.EnvironmentVariables["UV_LINK_MODE"] = "copy";
                startInfo.EnvironmentVariables["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1";
                startInfo.EnvironmentVariables["PYTHONUTF8"] = "1";

                using (Process process = Process.Start(startInfo))
                {
                    string output = process.StandardOutput.ReadToEnd();
                    string error = process.StandardError.ReadToEnd();
                    process.WaitForExit();
                    if (process.ExitCode != 0)
                    {
                        string details = string.IsNullOrWhiteSpace(error) ? output : error;
                        throw new InvalidOperationException(details.Trim());
                    }
                }
            }

            private static void StartApplication()
            {
                string pythonw = Path.Combine(EnvironmentDirectory, "Scripts", "pythonw.exe");
                ProcessStartInfo startInfo = new ProcessStartInfo
                {
                    FileName = pythonw,
                    Arguments = "-m voicemaster",
                    WorkingDirectory = AppDirectory,
                    UseShellExecute = false,
                    CreateNoWindow = true
                };
                startInfo.EnvironmentVariables["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1";
                startInfo.EnvironmentVariables["PYTHONUTF8"] = "1";
                Process.Start(startInfo);
            }

            private static bool IsApplicationReady()
            {
                return Directory.Exists(AppDirectory) && File.Exists(PythonExecutable());
            }

            private static string PythonExecutable()
            {
                return Path.Combine(EnvironmentDirectory, "Scripts", "python.exe");
            }

            private static string Quote(string value)
            {
                return "\"" + value.Replace("\"", "\\\"") + "\"";
            }

            private static void CopyDirectory(string source, string destination)
            {
                Directory.CreateDirectory(destination);
                foreach (string file in Directory.GetFiles(source))
                {
                    File.Copy(file, Path.Combine(destination, Path.GetFileName(file)), true);
                }
                foreach (string directory in Directory.GetDirectories(source))
                {
                    CopyDirectory(directory, Path.Combine(destination, Path.GetFileName(directory)));
                }
            }

            private static void DeleteDirectory(string path)
            {
                if (Directory.Exists(path))
                {
                    Directory.Delete(path, true);
                }
            }

            private void SetStatus(string message)
            {
                if (status.InvokeRequired)
                {
                    status.Invoke((Action<string>)SetStatus, message);
                    return;
                }
                status.Text = message;
            }

            private void CloseSafely()
            {
                if (InvokeRequired)
                {
                    Invoke((Action)CloseSafely);
                    return;
                }
                Close();
            }
        }
    }
}
