// The Approve dialog: modal, shows exactly what will run, and Deny is the default
// button so pressing Enter never approves by accident.

using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Microsoft.VisualStudio.PlatformUI;
using Microsoft.VisualStudio.Shell;

namespace AutoDebug.VisualStudio
{
    static class ApprovalDialog
    {
        public static bool Show(string title, string detail)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            var window = new DialogWindow
            {
                Title = "AutoDebug",
                Width = 760,
                Height = 600,
                MinWidth = 480,
                MinHeight = 320,
                WindowStartupLocation = WindowStartupLocation.CenterOwner,
                ResizeMode = ResizeMode.CanResizeWithGrip,
                HasMaximizeButton = false,
                HasMinimizeButton = false,
            };
            var heading = new TextBlock { Text = title, FontWeight = FontWeights.SemiBold, FontSize = 14, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 0, 0, 10) };
            var details = new TextBox
            {
                Text = detail,
                IsReadOnly = true,
                TextWrapping = TextWrapping.Wrap,
                AcceptsReturn = true,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                FontFamily = new FontFamily("Consolas"),
            };
            var approve = new Button { Content = "Approve", MinWidth = 96, Margin = new Thickness(0, 0, 8, 0), Padding = new Thickness(12, 4, 12, 4) };
            var deny = new Button { Content = "Deny", MinWidth = 96, IsDefault = true, IsCancel = true, Padding = new Thickness(12, 4, 12, 4) };
            approve.Click += (sender, args) => window.DialogResult = true;
            deny.Click += (sender, args) => window.DialogResult = false;
            var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 12, 0, 0) };
            buttons.Children.Add(approve);
            buttons.Children.Add(deny);
            var layout = new DockPanel { Margin = new Thickness(16), LastChildFill = true };
            DockPanel.SetDock(heading, Dock.Top);
            DockPanel.SetDock(buttons, Dock.Bottom);
            layout.Children.Add(heading);
            layout.Children.Add(buttons);
            layout.Children.Add(details);
            window.Content = layout;
            return window.ShowModal() == true;
        }
    }
}
