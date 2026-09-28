pragma Singleton
import QtQuick

// Single source of truth for the flat/rounded/light-grey-black-yellow-blue look
// described in the plan's "Visual design / theming" section. Every screen and
// component reads its colors, radii and spacing from here so the look stays
// consistent and easy to retune later without touching each file.
QtObject {
    // Base surfaces / text.
    readonly property color colorBackground: "#e8eaed" // light grey page background
    readonly property color colorSurface: "#f7f8fa"    // one step lighter - cards/fields
    readonly property color colorText: "#1c1e21"        // near-black
    readonly property color colorTextMuted: "#6b7280"

    // Brief accent colors.
    readonly property color colorAccentBlue: "#2563eb"   // primary actions (Install/Save)
    readonly property color colorAccentYellow: "#f2b705"  // secondary/attention

    // Necessary but unspecified-by-the-brief colors.
    readonly property color colorBorder: "#d3d6db"   // flat field/card outlines
    readonly property color colorDanger: "#dc2626"   // destructive actions (Delete/Uninstall)
    readonly property color colorSuccess: "#1f9254"  // "Installed" status

    // Slightly rounded, never pill-shaped.
    readonly property real radiusSmall: 4
    readonly property real radiusMedium: 10

    readonly property real spacingSmall: 6
    readonly property real spacingMedium: 12
    readonly property real spacingLarge: 20
}
