# IHHT gas mixer

Prototype of a gas mixer for IHHT. Not for use on a person.

The framework is a bore crop, labeling, and a configuration search over HOG + SVM and glint.

The camera looks at one rotameter tube. The tube quad is warped into a strip, and the search stays inside the bore. A few sweeps are labeled by hand: each click is the center of the float. Every candidate is a method plus its settings. It is fit on one sweep plus the steady clips, then scored on the other sweep with those settings frozen. The sweeps then swap.

## HOG + SVM

Each candidate patch inside the bore is described by a histogram of oriented gradients. A linear support-vector machine scores that description.

Training uses one sweep plus the steady clips. Patches on and just beside each click are the positive examples. Patches far from the click are the negative ones. A second pass adds the patches the first model wrongly called the ball. The fitted SVM is frozen and scored on the other sweep.

The settings in the search are the patch size and how far the tracker looks from the last hit. The SVM is part of the method.

## Glint

Glint is a matched filter, a fixed template. The template is a small bright disk, the LED speck, inside a larger dark ring, the body of the float. Sliding that template over the bore and taking the strongest response is the detection.

The clicks are used afterwards, as one fixed shift from that bright speck down to the center of the ball, measured on the training sweep. The settings are the strip height, the speck radius, and the dark-ring radius.
