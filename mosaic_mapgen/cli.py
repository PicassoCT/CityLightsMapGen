import argparse
import json
import sys
from pathlib import Path
from .profiles import Config
from .geography import load_city, google_center, fetch_osm
from .generator import generate
from .export import export

def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate deterministic mirrored Spring/Recoil city maps for MOSAIC")
    commands = parser.add_subparsers(dest="command",required=True)
    fetch = commands.add_parser("fetch",help="Select a Google Maps viewport and save an OSM snapshot")
    fetch.add_argument("--google-view",required=True)
    fetch.add_argument("--radius-m",type=float,required=True)
    fetch.add_argument("--out",type=Path,required=True)
    build = commands.add_parser("build",help="Offline generation, balance audit and playable SDZ export")
    build.add_argument("--city",type=Path,required=True)
    build.add_argument("--config",type=Path,required=True)
    build.add_argument("--out",type=Path,required=True)
    install = commands.add_parser("install-game-adapter",help="Preview or apply checked MOSAIC integration patches")
    install.add_argument("--game-dir",type=Path,required=True)
    install.add_argument("--apply",action="store_true",help="Write adapter and patches after complete compatibility validation")
    args = parser.parse_args(argv)
    try:
        if args.command=="fetch":
            if args.out.exists():
                raise ValueError("Snapshot destination already exists")
            fetch_osm(google_center(args.google_view),args.radius_m,args.out)
            print(f"Saved OSM snapshot: {args.out}")
        elif args.command=="build":
            config,city = Config.load(args.config),load_city(args.city)
            generated = generate(config,city)
            if not generated.report["passed"]:
                print(json.dumps(generated.report,indent=2),file=sys.stderr)
                return 2
            archive = export(generated,args.out)
            print(json.dumps({"map":str(archive),"buildings":generated.report["building_count"],"objectives":generated.report["objective_count"],"balanced":True},indent=2))
        else:
            from .integration import install_adapter
            print(json.dumps(install_adapter(args.game_dir,args.apply),indent=2))
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print(f"mosaic-mapgen: {exc}",file=sys.stderr)
        return 2
    return 0

if __name__=="__main__":
    sys.exit(main())
