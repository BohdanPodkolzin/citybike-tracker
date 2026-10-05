# dotenv reader
def load_dotenv(path)
  return {} unless File.exist?(path)
  File.readlines(path, chomp: true).each_with_object({}) do |line, vars|
    line = line.strip
    next if line.empty? || line.start_with?("#")
    key, value = line.split("=", 2)
    next if value.nil?
    vars[key.strip] = value.strip.sub(/\A(["'])(.*)\1\z/, '\2')
  end
end

DOTENV = load_dotenv(File.join(__dir__, ".env"))

def get_env(key, default = nil) # default - optional param
  value = ENV[key] || DOTENV[key] || default
  value.to_s.empty? ? nil : value.to_s
end

# validation db password
if (ARGV & %w[up provision reload]).any? && get_env("DB_PASSWORD").nil?
  abort "DB_PASSWORD is missing. Copy .env.example to .env and set it."
end

# --- network
BOX = get_env("VAGRANT_BOX", "bento/ubuntu-22.04")
LAN_PREFIX = get_env("LAN_PREFIX", "192.168.0")
NETMASK    = "255.255.255.0"
BRIDGE = get_env("BRIDGE_INTERFACE")
HOST_NUMBERS = {
  "db"      => 50,
  "fetcher" => 51,
  "history" => 52,
  "ui"      => 53,
}.freeze

def ip_of(name)
  "#{LAN_PREFIX}.#{HOST_NUMBERS.fetch(name)}"
end

VMS = [
  {
    name: "db",
    ip: ip_of("db"),
    cpus: 1,
    memory: 1024,
    script: "provision/db.sh",
    env: {
      "DB_NAME"      => get_env("DB_NAME", "citybikes").to_s,
      "DB_USER"      => get_env("DB_USER", "citybikes_app").to_s,
      "DB_PASSWORD"  => get_env("DB_PASSWORD").to_s,
      "DB_PORT"      => get_env("DB_PORT", "5432").to_s,
      "ALLOWED_CIDR" => get_env("ALLOWED_CIDR", "#{LAN_PREFIX}.0/24").to_s,
    },
  },
].freeze

# --- build

Vagrant.configure("2") do |config|
    config.vm.box = BOX
    config.vm.box_check_update = false

    # DO NOT synchronize the actual dir with the VMs vagrant dir
    config.vm.synced_folder ".", "/vagrant", disabled: true

    VMS.each do |vm|
        config.vm.define vm[:name] do |node|
        node.vm.hostname = "citybikes-#{vm[:name]}"

        # briged
        net_opts = { ip: vm[:ip], netmask: NETMASK }
        net_opts[:bridge] = BRIDGE if BRIDGE
        node.vm.network "public_network", **net_opts


        node.vm.provider "virtualbox" do |vb|
            vb.name   = "citybikes-#{vm[:name]}"
            vb.cpus   = vm[:cpus]
            vb.memory = vm[:memory]
        end


      node.vm.provision "common",  type: "shell", path: "provision/common.sh", env: { "VM_IP" => vm[:ip] }
      node.vm.provision "service", type: "shell", path: vm[:script], env: vm[:env]
      node.vm.post_up_message = "==> citybikes-#{vm[:name]} is at #{vm[:ip]}"
    end
  end
end