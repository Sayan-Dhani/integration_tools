#!/usr/bin/env python3
import ROOT
import sys
import argparse
import math

layer_spacers = {0: 26, 1: 40, 2: 40, 3: 40, 4: 26}


def get_xy_strip(hybrid_id, address, fe_id):
    # Logic from drawEvent.C:
    # X: -int(SCluster_HybridId/2)*500+spacer
    # Y: (SCluster_HybridId%2==0)?(SCluster_Address+SCluster_FrontEndId*120):(960-(SCluster_Address+SCluster_FrontEndId*120))
    layer = int(hybrid_id / 2)
    spacer = layer_spacers.get(layer, 40)
    x = -layer * 500 + spacer
    y_val = address + fe_id * 120
    if hybrid_id % 2 == 0:
        y = y_val
    else:
        y = 960 - y_val
    return x, y


def get_xy_pixel(hybrid_id, address, fe_id):
    # Logic from drawEvent.C:
    # X: -int(PCluster_HybridId/2)*500
    # Y: (PCluster_HybridId%2==0)?(PCluster_Address+PCluster_FrontEndId*120):(960-(PCluster_Address+PCluster_FrontEndId*120))
    x = -int(hybrid_id / 2) * 500
    y_val = address + fe_id * 120
    if hybrid_id % 2 == 0:
        y = y_val
    else:
        y = 960 - y_val
    return x, y


def get_xy_stub(hybrid_id, column, fe_id):
    # Logic from drawEvent.C:
    # X: -int(Stub_HybridId/2)*500+spacer/2
    # Y: (Stub_HybridId%2==0)?(Stub_Column/2+Stub_FrontEndId*120):(960-(Stub_Column/2+Stub_FrontEndId*120))
    layer = int(hybrid_id / 2)
    spacer = layer_spacers.get(layer, 40)
    x = -layer * 500 + spacer / 2.0
    y_val = column / 2.0 + fe_id * 120
    if hybrid_id % 2 == 0:
        y = y_val
    else:
        y = 960 - y_val
    return x, y


def get_z_pixel(hybrid_id, zpos):
    # Logic from drawEvent.C:
    # (PCluster_HybridId%2==0)?PCluster_Zpos:32-PCluster_Zpos
    # Scaled by 10 for 3D view
    if hybrid_id % 2 == 0:
        z = zpos
    else:
        z = 32 - zpos
    return z * 10.0


def get_z_stub(hybrid_id, row):
    # Logic from drawEvent.C:
    # (Stub_HybridId%2==0)?Stub_Row:32-Stub_Row
    # Scaled by 10 for 3D view
    if hybrid_id % 2 == 0:
        z = row
    else:
        z = 32 - row
    return z * 10.0


def draw_event(tree, entry, canvas):
    tree.GetEntry(entry)

    canvas.Clear()
    canvas.Divide(2, 1)

    # --- Pad 1: 3D View (Left) ---
    pad_3d = canvas.cd(1)
    # resize it to leave top 10% free
    pad_3d.SetPad(0.0, 0.0, 0.5, 0.9)
    # Create TView3D
    view = ROOT.TView.CreateView(1)

    # Center of the 5 modules
    # Modules at 0, -500, -1000, -1500, -2000
    center_real_y = -1000.0
    center_real_x = 480.0  # Middle of 0-960
    center_real_z = 160.0  # Middle of 0-320

    # Mapping: (Real X, Real Z, Real Y) -> (3D X, 3D Y, 3D Z)
    center_x = center_real_x
    center_y = center_real_z
    center_z = center_real_y

    # Define a view range centered on this point
    range_dx = 500  # +/- 500 (Real X width is 960)
    range_dy = 300  # +/- 250 (Real Z height is 320)
    range_dz = 1100  # +/- 1500 (Real Y height is ~2200)

    view.SetRange(
        center_x - range_dx,
        center_y - range_dy,
        center_z - range_dz,
        center_x + range_dx,
        center_y + range_dy,
        center_z + range_dz,
    )
    view.ShowAxis()

    # Store primitives to prevent garbage collection
    canvas.primitives = []

    # Helper to draw a 3D box from two opposite corners in Real coordinates
    def draw_box_real(x1, z1, y1, x2, z2, y2, color):
        # Map Real (X, Z, Y) -> 3D (X, Y, Z)
        # 3D X = Real X
        # 3D Y = Real Z
        # 3D Z = Real Y

        # Corners
        p0 = (x1, z1, y1)
        p1 = (x2, z1, y1)
        p2 = (x2, z2, y1)
        p3 = (x1, z2, y1)
        p4 = (x1, z1, y2)
        p5 = (x2, z1, y2)
        p6 = (x2, z2, y2)
        p7 = (x1, z2, y2)

        # Draw edges
        # Bottom face
        l = ROOT.TPolyLine3D(5)
        l.SetPoint(0, p0[0], p0[1], p0[2])
        l.SetPoint(1, p1[0], p1[1], p1[2])
        l.SetPoint(2, p2[0], p2[1], p2[2])
        l.SetPoint(3, p3[0], p3[1], p3[2])
        l.SetPoint(4, p0[0], p0[1], p0[2])
        l.SetLineColor(color)
        l.Draw()
        canvas.primitives.append(l)

        # Top face
        l2 = ROOT.TPolyLine3D(5)
        l2.SetPoint(0, p4[0], p4[1], p4[2])
        l2.SetPoint(1, p5[0], p5[1], p5[2])
        l2.SetPoint(2, p6[0], p6[1], p6[2])
        l2.SetPoint(3, p7[0], p7[1], p7[2])
        l2.SetPoint(4, p4[0], p4[1], p4[2])
        l2.SetLineColor(color)
        l2.Draw()
        canvas.primitives.append(l2)

        # Verticals
        for pa, pb in [(p0, p4), (p1, p5), (p2, p6), (p3, p7)]:
            l3 = ROOT.TPolyLine3D(2)
            l3.SetPoint(0, pa[0], pa[1], pa[2])
            l3.SetPoint(1, pb[0], pb[1], pb[2])
            l3.SetLineColor(color)
            l3.Draw()
            canvas.primitives.append(l3)

    # Draw 5 Modules (Fixed)
    for i in range(5):
        # Base Real Y for this module
        real_y = float(-i * 500)
        spacer = layer_spacers.get(i, 40)

        # Draw module frame (Real X: 0-960, Real Z: 0-320, Thickness: 3?)
        # User said "draw also the modules without hits".
        # Let's draw them as thin frames or boxes.
        draw_box_real(0.0, 0.0, real_y, 960.0, 320.0, real_y + 3.0, ROOT.kGray)

        # Strips part (offset spacer in Real Y)
        draw_box_real(
            0.0, 0.0, real_y + spacer, 960.0, 320.0, real_y + spacer + 3.0, ROOT.kGray
        )

    # Helper to safely get list/array
    def get_collection(obj, name):
        if hasattr(obj, name):
            return getattr(obj, name)
        return []

    s_hids = get_collection(tree, "SCluster_HybridId")
    p_hids = get_collection(tree, "PCluster_HybridId")
    st_hids = get_collection(tree, "Stub_HybridId")

    # Draw Strips as Boxes
    s_addr = get_collection(tree, "SCluster_Address")
    s_fe = get_collection(tree, "SCluster_FrontEndId")
    s_width = get_collection(tree, "SCluster_Width")

    n_strips = len(s_hids)
    for i in range(n_strips):
        hid = int(s_hids[i])
        addr = int(s_addr[i])
        fe = int(s_fe[i])
        width = float(s_width[i]) if s_width else 1.0

        real_y, real_x = get_xy_strip(hid, addr, fe)

        # Determine Real Z range based on parity
        if hid % 2 == 0:
            real_z_start = 0.0
            real_z_end = 160.0
            # Even: Real X increases with Address?
            # Formula: address + fe*120.
            # So Real X = current_x.
            # Width extends to current_x + width.
            real_x_start = real_x
            real_x_end = real_x + width
        else:
            real_z_start = 160.0
            real_z_end = 320.0
            # Odd: Real X = 960 - (address + fe*120).
            # If address increases, Real X decreases.
            # Cluster starts at `address` and has `width`.
            # So it covers `address` to `address + width`.
            # Mapped: `960 - (address + width)` to `960 - address`.
            # `real_x - width` to `real_x`.
            real_x_start = real_x - width
            real_x_end = real_x

        # Draw Box
        # Thickness 3
        draw_box_real(
            real_x_start,
            real_z_start,
            real_y,
            real_x_end,
            real_z_end,
            real_y + 3.0,
            ROOT.kRed,
        )

    # Draw Pixels as Boxes
    p_addr = get_collection(tree, "PCluster_Address")
    p_fe = get_collection(tree, "PCluster_FrontEndId")
    p_zpos = get_collection(tree, "PCluster_Zpos")
    p_width = get_collection(tree, "PCluster_Width")

    n_pixels = len(p_hids)
    for i in range(n_pixels):
        hid = int(p_hids[i])
        addr = int(p_addr[i])
        fe = int(p_fe[i])
        z_raw = float(p_zpos[i])
        width = float(p_width[i]) if p_width else 1.0

        real_y, real_x = get_xy_pixel(hid, addr, fe)
        real_z = get_z_pixel(hid, z_raw)

        # Pixel Z Length = 10 units (1 pitch)
        # Parity handling for X and Z directions

        if hid % 2 == 0:
            # Even
            real_x_start = real_x
            real_x_end = real_x + width

            # Z: Zpos -> Zpos*10.
            # Covers Zpos to Zpos+1 -> Z*10 to (Z+1)*10.
            real_z_start = real_z
            real_z_end = real_z + 10.0
        else:
            # Odd
            real_x_start = real_x - width
            real_x_end = real_x

            # Z: 32 - Zpos -> (32-Zpos)*10.
            # If Zpos increases, Real Z decreases.
            # Covers Zpos to Zpos+1.
            # Mapped: 32-(Zpos+1) to 32-Zpos.
            # (32-Zpos)*10 - 10 to (32-Zpos)*10.
            real_z_start = real_z - 10.0
            real_z_end = real_z

        draw_box_real(
            real_x_start,
            real_z_start,
            real_y,
            real_x_end,
            real_z_end,
            real_y + 3.0,
            ROOT.kBlue,
        )

    # Draw Stubs as Points (Removed in favor of lines)
    # st_col = get_collection(tree, "Stub_Column")
    # st_fe = get_collection(tree, "Stub_FrontEndId")
    # st_row = get_collection(tree, "Stub_Row")
    #
    # n_stubs = len(st_hids)
    # if n_stubs > 0:
    #     pm_stub = ROOT.TPolyMarker3D(n_stubs)
    #     pm_stub.SetMarkerStyle(22)
    #     pm_stub.SetMarkerColor(ROOT.kGreen + 2)
    #     pm_stub.SetMarkerSize(1.2)
    #
    #     for i in range(n_stubs):
    #         hid = int(st_hids[i])
    #         col = float(st_col[i])
    #         fe = int(st_fe[i])
    #         row = float(st_row[i])
    #
    #         real_y, real_x = get_xy_stub(hid, col, fe)
    #         real_z = get_z_stub(hid, row)
    #
    #         # Mapping: (Real X, Real Z, Real Y)
    #         pm_stub.SetPoint(i, real_x, real_z, real_y)
    #     pm_stub.Draw()

    # Draw Stubs as Vertical Lines with Bending
    st_col = get_collection(tree, "Stub_Column")
    st_fe = get_collection(tree, "Stub_FrontEndId")
    st_row = get_collection(tree, "Stub_Row")
    st_bend = get_collection(tree, "Stub_Bend")

    # Lookup table for bending
    # Indices 5-13 map to offsets
    bend_lut = {
        5: -4.0,  # DM8
        6: -3.5,  # M76
        7: -2.5,  # M54
        8: -1.5,  # M32
        9: -0.5,  # M10
        10: 0.5,  # P12
        11: 1.5,  # P34
        12: 2.5,  # P56
        13: 3.5,  # P78
    }

    n_stubs = len(st_hids)
    print(f"Drawing {n_stubs} stubs")
    for i in range(n_stubs):
        hid = int(st_hids[i])
        col = float(st_col[i])
        fe = int(st_fe[i])
        row = float(st_row[i])
        bend_code = int(st_bend[i]) if st_bend else 0
        # take only first 3 bits
        bend_code = bend_code & 0x7

        offset = bend_lut.get(bend_code, 0.0)
        print(f"Bend code: {bend_code}, offset: {offset}")
        # flip sign based on hybrid parity
        if hid % 2 == 1:
            offset = -offset
        real_y, real_x = get_xy_stub(hid, col, fe)
        real_z = get_z_stub(hid, row)

        # Stub connects Pixel Layer (Real Y) to Strip Layer (Real Y + 40? or similar distance)
        # We assume the stub is anchored at the Pixel position (real_x, real_z, real_y)
        # And connects to (real_x + offset, real_z, real_y + 40)

        # Point 1 (Pixel Layer)
        p1_real_x = real_x
        p1_real_z = real_z
        p1_real_y = real_y

        # Point 2 (Strip Layer)
        spacer = layer_spacers.get(int(hid / 2), 40)
        p2_real_x = real_x + offset
        p2_real_z = real_z
        p2_real_y = real_y + spacer

        # Draw Line
        # Mapping: (Real X, Real Z, Real Y) -> (3D X, 3D Y, 3D Z)
        line = ROOT.TPolyLine3D(2)
        line.SetPoint(0, p1_real_x, p1_real_z, p1_real_y)
        line.SetPoint(1, p2_real_x, p2_real_z, p2_real_y)
        line.SetLineColor(ROOT.kGreen + 2)
        line.SetLineWidth(2)
        line.Draw()
        canvas.primitives.append(line)

    # --- Custom Track Drawing ---

    # Group stubs by layer
    stubs_by_layer = {}
    for i in range(n_stubs):
        hid = int(st_hids[i])
        layer = int(hid / 2)
        if layer not in stubs_by_layer:
            stubs_by_layer[layer] = []
        stubs_by_layer[layer].append(i)

    sorted_layers = sorted(stubs_by_layer.keys())
    if len(sorted_layers) >= 2:
        min_layer = sorted_layers[0]
        max_layer = sorted_layers[-1]

        # Use first stub in min/max layer
        idx1 = stubs_by_layer[min_layer][0]
        idx2 = stubs_by_layer[max_layer][0]

        hid1 = int(st_hids[idx1])
        col1 = float(st_col[idx1])
        fe1 = int(st_fe[idx1])
        row1 = float(st_row[idx1])

        hid2 = int(st_hids[idx2])
        col2 = float(st_col[idx2])
        fe2 = int(st_fe[idx2])
        row2 = float(st_row[idx2])

        y1, x1 = get_xy_stub(
            hid1, col1, fe1
        )  # Note: get_xy_stub returns (real_y, real_x)
        z1 = get_z_stub(hid1, row1)

        y2, x2 = get_xy_stub(hid2, col2, fe2)
        z2 = get_z_stub(hid2, row2)

        # Draw Track Line
        tline = ROOT.TPolyLine3D(2)
        tline.SetPoint(0, x1, z1, y1)  # 3D: x=real_x, y=real_z, z=real_y
        tline.SetPoint(1, x2, z2, y2)
        tline.SetLineColor(ROOT.kGray)
        tline.SetLineWidth(2)
        tline.Draw()
        canvas.primitives.append(tline)

        # Draw dots in intermediate layers
        if abs(y2 - y1) > 1e-5:
            for layer in range(min_layer + 1, max_layer):
                spacer = layer_spacers.get(layer, 40)

                # Sensor 1: y = -layer * 500
                y_s1 = -layer * 500.0
                t_s1 = (y_s1 - y1) / (y2 - y1)
                x_s1 = x1 + t_s1 * (x2 - x1)
                z_s1 = z1 + t_s1 * (z2 - z1)

                pm1 = ROOT.TPolyMarker3D(1)
                pm1.SetPoint(0, x_s1, z_s1, y_s1)
                pm1.SetMarkerStyle(20)
                pm1.SetMarkerColor(ROOT.kGray)
                pm1.SetMarkerSize(1.0)
                pm1.Draw()
                canvas.primitives.append(pm1)

                # Sensor 2: y = -layer * 500 + spacer
                y_s2 = -layer * 500.0 + spacer
                t_s2 = (y_s2 - y1) / (y2 - y1)
                x_s2 = x1 + t_s2 * (x2 - x1)
                z_s2 = z1 + t_s2 * (z2 - z1)

                pm2 = ROOT.TPolyMarker3D(1)
                pm2.SetPoint(0, x_s2, z_s2, y_s2)
                pm2.SetMarkerStyle(20)
                pm2.SetMarkerColor(ROOT.kGray)
                pm2.SetMarkerSize(1.0)
                pm2.Draw()
                canvas.primitives.append(pm2)

    # --- Pad 2: 2D Views (Right) ---
    pad_right = canvas.cd(2)
    pad_right.Divide(1, 2)

    # --- Pad 2_1: XY View (Top Right) ---
    pad_xy = pad_right.cd(1)
    pad_xy.SetGridx()
    pad_xy.SetGridy()

    # Background histogram for XY
    h_xy = ROOT.TH2F("h_xy", "XY View", 1000, -100, 1000, 1000, -2200, 100)
    h_xy.SetStats(0)
    h_xy.Draw()

    # SCluster (Strips) - Red
    tree.SetMarkerStyle(20)
    tree.SetMarkerColor(ROOT.kRed)
    tree.Draw(
        "-int(SCluster_HybridId/2)*500+( (int(SCluster_HybridId/2)==0 || int(SCluster_HybridId/2)==4) ? 26 : 40 ):(SCluster_HybridId%2==0)?(SCluster_Address+SCluster_FrontEndId*120):(960-(SCluster_Address+SCluster_FrontEndId*120))",
        f"Entry$=={entry}",
        "same",
    )

    # PCluster (Pixels) - Blue
    tree.SetMarkerStyle(21)
    tree.SetMarkerColor(ROOT.kBlue)
    tree.Draw(
        "-int(PCluster_HybridId/2)*500:(PCluster_HybridId%2==0)?(PCluster_Address+PCluster_FrontEndId*120):(960-(PCluster_Address+PCluster_FrontEndId*120))",
        f"Entry$=={entry}",
        "same",
    )

    # Stub - Green (lines showing bending)
    # Draw lines from pixel position to strip position with offset
    for i in range(n_stubs):
        hid = int(st_hids[i])
        col = float(st_col[i])
        fe = int(st_fe[i])
        bend_code = int(st_bend[i]) if st_bend else 0
        bend_code = bend_code & 0x7
        offset = bend_lut.get(bend_code, 0.0)
        print(f"Bend code: {bend_code}, offset: {offset}")
        # flip sign based on hybrid parity
        if hid % 2 == 1:
            offset = -offset
        # Pixel position (X coordinate)
        spacer = layer_spacers.get(int(hid / 2), 40)
        real_y_pixel, real_x_pixel = get_xy_pixel(hid, int(col / 2), fe)
        real_y_pixel -= spacer
        real_x_pixel -= offset
        # Strip position (X coordinate with offset)
        real_y_strip = real_y_pixel + spacer * 3
        real_x_strip = real_x_pixel + offset * 3

        # Draw line in XY view
        line_xy = ROOT.TLine(real_x_pixel, real_y_pixel, real_x_strip, real_y_strip)
        line_xy.SetLineColor(ROOT.kGreen + 2)
        line_xy.SetLineWidth(2)
        line_xy.Draw()
        canvas.primitives.append(line_xy)

    # Legend
    leg = ROOT.TLegend(0.1, 0.5, 0.25, 0.65)
    gS = ROOT.TGraph()
    gS.SetMarkerStyle(20)
    gS.SetMarkerColor(ROOT.kRed)
    gS.SetTitle("SCluster")
    gP = ROOT.TGraph()
    gP.SetMarkerStyle(21)
    gP.SetMarkerColor(ROOT.kBlue)
    gP.SetTitle("PCluster")
    gStub = ROOT.TGraph()
    gStub.SetMarkerStyle(22)
    gStub.SetMarkerColor(ROOT.kGreen + 2)
    gStub.SetTitle("Stub")
    leg.AddEntry(gS, "SCluster", "p")
    leg.AddEntry(gP, "PCluster", "p")
    leg.AddEntry(gStub, "Stub", "p")
    leg.Draw()

    # --- Pad 2_2: Z View (Bottom Right) ---
    pad_z = pad_right.cd(2)
    pad_z.SetGridx()
    pad_z.SetGridy()

    h_z = ROOT.TH2F("h_z", "Z View", 1000, -5, 50, 1000, -2200, 100)
    h_z.SetStats(0)
    h_z.Draw()

    # PCluster (Pixels) - ZPos
    tree.SetMarkerStyle(21)
    tree.SetMarkerColor(ROOT.kBlue)
    tree.Draw(
        "-int(PCluster_HybridId/2)*500:(PCluster_HybridId%2==0)?PCluster_Zpos:32-PCluster_Zpos",
        f"Entry$=={entry}",
        "same",
    )

    # Stub - Row (triangles)
    tree.SetMarkerStyle(22)
    tree.SetMarkerColor(ROOT.kGreen + 2)
    tree.Draw(
        "-int(Stub_HybridId/2)*500+( (int(Stub_HybridId/2)==0 || int(Stub_HybridId/2)==4) ? 13 : 20 ):(Stub_HybridId%2==0)?Stub_Row:32-Stub_Row",
        f"Entry$=={entry}",
        "same",
    )

    canvas.Update()


def main():
    # Initialize TApplication to handle GUI events properly
    app = ROOT.TApplication("app", 0, 0)

    parser = argparse.ArgumentParser(description="Draw events from ROOT file")
    parser.add_argument("--input", "-i", required=True, help="Input ROOT file")
    parser.add_argument("--start", type=int, default=0, help="Start entry")
    args = parser.parse_args()

    f = ROOT.TFile.Open(args.input)
    if not f or f.IsZombie():
        print(f"Error opening file {args.input}")
        sys.exit(1)

    tree = f.Get("Events")
    if not tree:
        print("Error: Events tree not found")
        sys.exit(1)

    canvas = ROOT.TCanvas("c1", "Event Display", 1200, 800)

    n_entries = tree.GetEntries()
    print(f"Found {n_entries} entries.")

    import select
    import time

    # State variable to track button clicks
    button_clicked = [None]  # Use list so it can be modified in nested function

    # Define callback functions that will be called when buttons are clicked
    def on_prev_click():
        button_clicked[0] = "prev"

    def on_next_click():
        button_clicked[0] = "next"

    current_entry = args.start
    while current_entry < n_entries:
        print(f"Drawing entry {current_entry}...")
        draw_event(tree, current_entry, canvas)

        # Add buttons after drawing event (they need to be recreated after canvas.Clear())
        # Draw on the main canvas, not in a sub-pad
        canvas.cd(0)  # Select the main canvas

        prev_button = ROOT.TButton("Previous", "", 0.02, 0.92, 0.10, 0.97)
        prev_button.SetFillColor(ROOT.kGray + 1)
        prev_button.SetTextSize(0.5)
        prev_button.Draw()

        next_button = ROOT.TButton("Next", "", 0.12, 0.92, 0.20, 0.97)
        next_button.SetFillColor(ROOT.kGray + 1)
        next_button.SetTextSize(0.5)
        next_button.Draw()

        # Event counter display
        event_label = ROOT.TPaveText(0.22, 0.92, 0.38, 0.97, "NDC")
        event_label.SetFillColor(ROOT.kWhite)
        event_label.SetTextColor(ROOT.kBlack)
        event_label.SetTextAlign(22)
        event_label.SetTextSize(0.03)
        event_label.SetBorderSize(1)
        event_label.AddText(f"Event: {current_entry} / {n_entries - 1}")
        event_label.Draw()

        canvas.Update()

        print(
            f"Entry {current_entry}. Click buttons or press Enter for next, 'p' for previous, 'q' to quit."
        )

        # Reset button click state
        button_clicked[0] = None

        # Non-blocking wait loop
        while True:
            # Process ROOT events (GUI, Zooming, etc.)
            ROOT.gSystem.ProcessEvents()

            # Check if a button was clicked by checking if the selected object is one of our buttons
            # Only respond to actual button release events (kButton1Up = 1)
            event = ROOT.gPad.GetEvent()
            if event == 1:  # kButton1Up - mouse button released
                selected = ROOT.gPad.GetSelected()
                if selected:
                    if selected == prev_button:
                        print("Previous button clicked!")
                        current_entry = max(0, current_entry - 1)
                        ROOT.gPad.SetSelected(ROOT.nullptr)  # Clear selection
                        break  # Redraw
                    elif selected == next_button:
                        print("Next button clicked!")
                        current_entry = min(n_entries - 1, current_entry + 1)
                        ROOT.gPad.SetSelected(ROOT.nullptr)  # Clear selection
                        break  # Redraw

            # Check for input on stdin
            # Wait up to 20ms for input
            r, w, e = select.select([sys.stdin], [], [], 0.02)
            if r:
                user_input = sys.stdin.readline().strip()
                if user_input.lower() == "q":
                    sys.exit(0)
                elif user_input.lower() == "p":
                    current_entry = max(0, current_entry - 1)
                    break  # Redraw
                elif user_input.isdigit():
                    # Go to specific event
                    goto_entry = int(user_input)
                    if 0 <= goto_entry < n_entries:
                        current_entry = goto_entry
                        print(f"Going to event {current_entry}")
                    else:
                        print(
                            f"Invalid entry number. Must be between 0 and {n_entries - 1}"
                        )
                    break  # Redraw
                else:
                    current_entry += 1
                    break  # Redraw

            # No explicit sleep needed as select waits up to timeout


if __name__ == "__main__":
    main()
