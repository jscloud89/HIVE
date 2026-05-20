// ═══════════════════════════════════════════════════════
// SLAB VAULT STAND — spiced_slabs original design v2
// Parametric graded card display stand
// Compatible: PSA, BGS, CGC, SGC, TAG slabs + toploaders
//
// VARIANTS:
//   variant=0 → Pokéball (Pokemon collectors)
//   variant=1 → Star shield (sports cards)
//   variant=2 → Plain / blank front
//
// Engineer Agent — HIVE workspace
// ═══════════════════════════════════════════════════════

// ── PARAMETERS ──────────────────────────────────────────

// Slab dimensions
slab_w = 63;      // PSA: 63 | BGS: 65 | CGC: 64
slab_d = 10;      // PSA: 10 | BGS: 12 | CGC: 11

// Stand dimensions
base_w     = 82;
base_d     = 58;
base_h     = 9;
slot_depth = 24;
wall_t     = 3.8;
slot_tol   = 0.8;
front_lip  = 13;
tilt_angle = 10;

// Front emblem variant
// 0 = Pokéball  1 = Star/Shield  2 = Plain
variant = 0;

// Branding (bottom of base)
brand_text  = "spiced_slabs";
text_size   = 4.5;
text_depth  = 0.8;

// Feet recesses
foot_r = 4;
foot_d = 1.8;

// ── DERIVED ─────────────────────────────────────────────
slot_w = slab_w + slot_tol;
slot_t = slab_d + slot_tol;

// ── HELPERS ─────────────────────────────────────────────
module rounded_box(w, d, h, r=4) {
    hull() {
        for (x=[r, w-r])
        for (y=[r, d-r])
            translate([x,y,0])
                cylinder(r=r, h=h, $fn=36);
    }
}

// ── POKÉBALL EMBLEM ──────────────────────────────────────
module pokeball(cx, cy, z, r=10, depth=0.7) {
    translate([cx, cy, z]) {
        // Outer circle
        linear_extrude(depth)
            difference() {
                circle(r=r, $fn=60);
                circle(r=r-1.2, $fn=60);
            }
        // Center dividing line (horizontal)
        linear_extrude(depth)
            square([r*2, 1.4], center=true);
        // Center button circle
        linear_extrude(depth+0.1)
            circle(r=2.8, $fn=36);
        // Center button inner
        color("white")
        translate([0,0,depth])
        linear_extrude(0.2)
            circle(r=1.6, $fn=36);
        // Top half fill line detail
        linear_extrude(depth*0.5)
            difference() {
                intersection() {
                    circle(r=r-1.3, $fn=60);
                    translate([0, 0.7])
                        square([r*2, r*2], center=true);
                }
                circle(r=r*0.45, $fn=36);
            }
    }
}

// ── STAR / SHIELD EMBLEM ─────────────────────────────────
module star(cx, cy, z, r_outer=9, r_inner=4, points=5, depth=0.7) {
    translate([cx, cy, z])
        linear_extrude(depth) {
            polygon([
                for (i=[0:points*2-1])
                    let(
                        angle = i * 180/points - 90,
                        r = (i % 2 == 0) ? r_outer : r_inner
                    )
                    [r*cos(angle), r*sin(angle)]
            ]);
        }
}

module shield(cx, cy, z, w=18, h=20, depth=0.7) {
    translate([cx, cy, z])
        linear_extrude(depth) {
            polygon([
                [-w/2, h*0.3],
                [-w/2, h/2],
                [0,    h/2],
                [w/2,  h/2],
                [w/2,  h*0.3],
                [w/2, -h*0.1],
                [0,   -h/2],
                [-w/2, -h*0.1]
            ]);
        }
}

// ── FRONT EMBLEM ─────────────────────────────────────────
module front_emblem(base_w, base_h, front_lip) {
    // Position on front face of base
    // Front face is at y=0, center x = base_w/2
    cx = base_w / 2;
    cy = 0;
    z  = base_h * 0.45;

    if (variant == 0) {
        // Pokéball
        rotate([90, 0, 0])
            translate([0, 0, -0.01])
                pokeball(cx, z, 0, r=10, depth=0.8);
    }
    else if (variant == 1) {
        // Star above shield
        rotate([90, 0, 0])
            translate([0, 0, -0.01]) {
                star(cx, z + 3, 0, r_outer=7, r_inner=3, points=5, depth=0.8);
                // "GRADED" text below star
                translate([cx, z - 5, 0])
                    linear_extrude(0.8)
                        text("GRADED",
                             size=3.5,
                             font="Liberation Sans:style=Bold",
                             halign="center",
                             valign="center");
            }
    }
    // variant==2: plain, no emblem
}

// ── BRAND TEXT (bottom of base) ──────────────────────────
module bottom_brand(base_w, base_d) {
    translate([base_w/2, base_d/2, -0.01])
        rotate([0, 180, 0])
            linear_extrude(text_depth + 0.01)
                text(brand_text,
                     size=text_size,
                     font="Liberation Sans:style=Bold Italic",
                     halign="center",
                     valign="center");
}

// ── FOOT RECESSES ────────────────────────────────────────
module feet(base_w, base_d) {
    margin = 9;
    for (x=[margin, base_w-margin])
    for (y=[margin, base_d-margin])
        translate([x, y, -0.01])
            cylinder(r=foot_r, h=foot_d+0.01, $fn=24);
}

// ── UPRIGHT COLUMN ───────────────────────────────────────
module upright() {
    col_w = base_w;
    col_d = slot_t + wall_t * 2;
    col_h = slot_depth + wall_t;

    difference() {
        // Outer column body
        rounded_box(col_w, col_d, col_h, r=2.5);

        // Inner slot cutout
        translate([(col_w - slot_w)/2, wall_t, -0.01])
            cube([slot_w, slot_t, slot_depth + 0.02]);

        // Top chamfer for easy slab insertion
        translate([(col_w - slot_w)/2 - 1.5, wall_t - 1.5, slot_depth - 4])
            hull() {
                cube([slot_w + 3, slot_t + 3, 0.1]);
                translate([-2.5, -2.5, 7])
                    cube([slot_w + 8, slot_t + 8, 0.1]);
            }
    }
}

// ── MAIN ASSEMBLY ────────────────────────────────────────
module slab_stand() {
    difference() {
        union() {
            // Base plate
            rounded_box(base_w, base_d, base_h, r=4);

            // Upright with tilt
            translate([0, front_lip, base_h])
                rotate([-tilt_angle, 0, 0])
                    upright();
        }

        // Foot recesses (from bottom)
        feet(base_w, base_d);

        // Brand text (recessed into bottom)
        bottom_brand(base_w, base_d);

        // Front emblem (recessed into front face)
        front_emblem(base_w, base_h, front_lip);
    }
}

// ── RENDER ───────────────────────────────────────────────
slab_stand();

// ── PRINT NOTES ──────────────────────────────────────────
// Orientation: flat base down, no supports needed
// Layer height: 0.12mm
// Walls: 3
// Infill: 15% gyroid
// Material: PLA (Marble White, Matte Black, Burnt Titanium)
//
// Generate variants:
//   Pokéball:  variant=0 (default)
//   Sports:    variant=1
//   Plain:     variant=2
//
//   PSA:       slab_w=63 slab_d=10
//   BGS:       slab_w=65 slab_d=12
//   CGC:       slab_w=64 slab_d=11
//   Toploader: slab_w=67 slab_d=1 slot_tol=1.5
