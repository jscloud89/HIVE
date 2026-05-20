// ═══════════════════════════════════════════════════════
// SLAB VAULT STAND — spiced_slabs original design
// Parametric graded card display stand
// Compatible: PSA, BGS, CGC, SGC, TAG slabs + toploaders
// Engineer Agent — HIVE workspace
// ═══════════════════════════════════════════════════════

// ── PARAMETERS (customize here) ─────────────────────────

// Slab dimensions (PSA default)
slab_w = 63;      // slab width mm
slab_h = 94;      // slab height mm
slab_d = 10;      // slab depth/thickness mm

// Stand dimensions
base_w       = 80;    // base width
base_d       = 55;    // base depth (front to back)
base_h       = 8;     // base height
slot_depth   = 22;    // how deep the slab sits in the slot
wall_t       = 3.5;   // wall thickness around slot
slot_tol     = 0.6;   // tolerance for slab fit (looser = easier insert)
front_lip    = 12;    // front lip depth in front of slot
back_wall    = 10;    // back wall thickness for stability

// Angle
tilt_angle   = 10;    // degrees backward tilt (0 = straight up)

// Text / branding
show_text    = true;
brand_text   = "spiced_slabs";
text_size    = 5;
text_depth   = 0.6;

// Feet (rubber foot recesses)
show_feet    = true;
foot_r       = 4;
foot_d       = 1.5;   // recess depth

// ── DERIVED ─────────────────────────────────────────────
slot_w = slab_w + slot_tol;
slot_t = slab_d + slot_tol;
total_h = base_h + slot_depth + wall_t;

// ── MODULES ─────────────────────────────────────────────

module rounded_box(w, d, h, r=3) {
    hull() {
        for (x = [r, w-r])
        for (y = [r, d-r])
            translate([x, y, 0])
                cylinder(r=r, h=h, $fn=32);
    }
}

module slot_cutout() {
    // Main slab slot - slightly tapered at top for easy insertion
    translate([(base_w - slot_w) / 2, front_lip, base_h])
        union() {
            // Main slot
            cube([slot_w, slot_t, slot_depth + 1]);
            // Chamfer at top for easy insertion
            translate([0, 0, slot_depth - 2])
                hull() {
                    cube([slot_w, slot_t, 0.1]);
                    translate([-2, -2, 4])
                        cube([slot_w + 4, slot_t + 4, 0.1]);
                }
        }
}

module brand_label() {
    if (show_text) {
        translate([base_w/2, base_d * 0.3, base_h])
            rotate([0, 0, 0])
            linear_extrude(text_depth + 0.01)
                text(brand_text,
                     size=text_size,
                     font="Liberation Sans:style=Bold",
                     halign="center",
                     valign="center");
    }
}

module foot_recesses() {
    if (show_feet) {
        margin = 8;
        for (x = [margin, base_w - margin])
        for (y = [margin, base_d - margin])
            translate([x, y, 0])
                cylinder(r=foot_r, h=foot_d + 0.01, $fn=24);
    }
}

module cable_channel() {
    // Optional: small channel on back for cable management
    // (useful for display shelf builds)
    translate([base_w/2 - 4, base_d - 2, 2])
        cube([8, 4, base_h]);
}

// ── MAIN BODY ────────────────────────────────────────────
module slab_stand() {
    difference() {
        union() {
            // Base plate
            rounded_box(base_w, base_d, base_h, r=4);

            // Upright column with tilt
            translate([0, front_lip, base_h])
                rotate([-tilt_angle, 0, 0])
                    difference() {
                        // Outer column
                        rounded_box(base_w, slot_t + wall_t * 2, slot_depth + wall_t, r=2);

                        // Inner slot (carved out)
                        translate([(base_w - slot_w) / 2, wall_t, 0])
                            cube([slot_w, slot_t, slot_depth + wall_t + 1]);

                        // Top chamfer for easy slab insertion
                        translate([(base_w - slot_w) / 2 - 1, wall_t - 1, slot_depth - 3])
                            hull() {
                                cube([slot_w + 2, slot_t + 2, 0.1]);
                                translate([-2, -2, 6])
                                    cube([slot_w + 6, slot_t + 6, 0.1]);
                            }
                    }
        }

        // Carve out foot recesses from bottom
        foot_recesses();

        // Branding text on front face of base
        brand_label();
    }
}

// ── RENDER ───────────────────────────────────────────────
slab_stand();

// ── NOTES ────────────────────────────────────────────────
// Print settings:
//   Layer height: 0.12mm (quality) or 0.16mm (speed)
//   Walls: 3
//   Infill: 15% gyroid
//   Supports: None needed
//   Orientation: Print as-is (flat base down)
//
// Filament: PLA (Marble White, Matte Black, Burnt Titanium)
//
// Variants to generate:
//   PSA:  slab_w=63, slab_d=10  (default)
//   BGS:  slab_w=65, slab_d=12
//   CGC:  slab_w=64, slab_d=11
//   TAG:  slab_w=63, slab_d=10
//   Toploader: slab_w=67, slab_d=1.5, slot_tol=1.0
