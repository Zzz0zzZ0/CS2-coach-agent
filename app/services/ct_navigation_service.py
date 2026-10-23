"""Bounded assignment to existing NAV surfaces; never fill gaps or alter connectivity."""

import math

import numpy as np


class NavigationLocator:
    def __init__(self, areas):
        triangles, identities = [], []
        for area in areas:
            corners = np.asarray(area["corners"], dtype=float)
            if corners.ndim != 2 or corners.shape[1] != 3 or len(corners) < 3 or not np.isfinite(corners).all():
                raise ValueError("Finite NAV polygons with at least three corners required")
            if area["hull_index"] != 0:
                continue
            for i in range(1, len(corners) - 1):
                triangles.append(corners[[0, i, i + 1]])
                identities.append(area["area_id"])
        if not triangles:
            raise ValueError("No player-hull NAV polygons")
        self.triangles = np.asarray(triangles)
        self.identities = identities
        self.minimum = self.triangles[:, :, :2].min(1)
        self.maximum = self.triangles[:, :, :2].max(1)

    def locate(self, point, max_xy=32.0, max_z=64.0):
        point = np.asarray(point, dtype=float)
        if point.shape != (3,) or not np.isfinite(point).all() or not all(math.isfinite(v) and v >= 0 for v in (max_xy, max_z)):
            raise ValueError("Finite XYZ and nonnegative finite tolerances required")
        candidates = np.flatnonzero(((self.minimum - max_xy <= point[:2]) & (point[:2] <= self.maximum + max_xy)).all(1))
        best = None
        for k in candidates:
            a, b, c = self.triangles[k]
            u, v, w = b[:2] - a[:2], c[:2] - a[:2], point[:2] - a[:2]
            determinant = u[0] * v[1] - u[1] * v[0]
            if abs(determinant) < 1e-8:
                continue
            s = (w[0] * v[1] - w[1] * v[0]) / determinant
            t = (u[0] * w[1] - u[1] * w[0]) / determinant
            if min(s, t, 1 - s - t) >= -1e-9:
                surface = a + s * (b - a) + t * (c - a)
            else:
                starts = np.asarray([a, b, c])
                edges = np.asarray([b - a, c - b, a - c])
                lengths = (edges[:, :2] ** 2).sum(1)
                fractions = np.divide(((point[:2] - starts[:, :2]) * edges[:, :2]).sum(1), lengths,
                                      out=np.zeros(3), where=lengths > 0).clip(0, 1)
                closest = starts + fractions[:, None] * edges
                surface = closest[((closest[:, :2] - point[:2]) ** 2).sum(1).argmin()]
            xy = float(np.linalg.norm(surface[:2] - point[:2]))
            dz = float(abs(surface[2] - point[2]))
            if xy > max_xy + 1e-8 or dz > max_z + 1e-8:
                continue
            score = (int(xy >= 1e-5), xy * xy + dz * dz, self.identities[k])
            if best is None or score < best[0]:
                best = (score, {"area_id": self.identities[k], "xy_residual": xy, "z_residual": dz,
                                "surface_position": surface.tolist(), "status": "inside" if xy < 1e-5 else "bounded_snap"})
        # shortcut: bounded snaps can cross thin walls; require collision/patch checks before navigation features enter training.
        return best[1] if best is not None else None
